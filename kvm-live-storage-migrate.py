#! /usr/bin/python3

import string
import time
import libvirt
import xml.etree.ElementTree as ET
import argparse

from pathlib import PurePosixPath

class DomainVolumeDesc:
    vol_type: string
    vol_path: string
    vol_name: string
    vol_pool: string

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('domain')
    parser.add_argument('--pool') #NOTE: libvirt managed volumes is currently not supported: https://gitlab.com/libvirt/libvirt/-/issues/384
    parser.add_argument('--filepath')
    parser.add_argument('--host', default='')
    parser.add_argument('--user')
    parser.add_argument('--ssh', action='store_const', const='+ssh', default='')
    parser.add_argument('--session', default='system')

    return parser.parse_args()

ARGS = parse_args()
SEPARATOR = "----------"

def main():
    if ARGS.filepath is None == ARGS.pool is None:
        print("Either --filepath or --pool must be specified (but not both).")
        exit(1)

    connection_uri = f"qemu{ARGS.ssh}://"
    if ARGS.user is not None:
        connection_uri += f"{ARGS.user}@"
    connection_uri += f"{ARGS.host}/{ARGS.session}"

    try:
        connection = libvirt.open(connection_uri)
    except libvirt.libvirtError as error:
        print(f"Failed to open connection to hypervisor for URI \"{connection_uri}\".")
        printLibvirtErrorAndExit(error)

    try:
        domain = connection.lookupByName(ARGS.domain)
    except libvirt.libvirtError as error:
        printLibvirtErrorAndExit(error)

    xml: str = domain.XMLDesc(0 | libvirt.VIR_DOMAIN_XML_INACTIVE)
    volumes = getVolumes(xml)
    migrated_volumes = removeVolumesAlreadyMigrated(volumes, ARGS.pool, ARGS.filepath)

    printParsedInfo(domain.name(), volumes, migrated_volumes, ARGS.pool, ARGS.filepath)

    if not len(volumes):
        print(f"\nAll disks already migrated.")
        exit(0)

    devs_with_ongoing_jobs = checkForOngoingBlockCopy(domain, volumes.keys())
    if len(devs_with_ongoing_jobs):
        print(f"\nOngoing migration(s) found for {domain.name()}. Resuming...")
        print(SEPARATOR)
        waitForAllBlockCopy(domain, devs_with_ongoing_jobs)
        pivotAllBlockCopyJobs(domain, devs_with_ongoing_jobs)
        print("Migration(s) finished. Execute the script again to start another.")
        exit(0)
    
    response = input("\nProceed? (y/N): ")
    if response.lower() != "y":
        exit(1)

    print(SEPARATOR)

    backup_filename = f"/tmp/{domain.name()}_backup.xml"
    print(f"Backing up domain XML to local file \"{backup_filename}\"")    

    with open(backup_filename, "w") as f:
        f.write(xml)

    domain.undefineFlags(0 | libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM)

    for target_dev, volume_description in volumes.items():
        dest_xml_param = getDestinationXML(volume_description, ARGS.pool, ARGS.filepath)
        domain.blockCopy(target_dev, dest_xml_param)
    waitForAllBlockCopy(domain, volumes.keys())
    pivotAllBlockCopyJobs(domain, volumes.keys())

    new_xml: str = domain.XMLDesc(0 | libvirt.VIR_DOMAIN_XML_INACTIVE)
    connection.defineXML(new_xml)
    print("Complete!")
        

def getVolumes(xml_desc: str) -> dict[str, DomainVolumeDesc]:
    domain_xml_root = ET.fromstring(xml_desc)
    devices_element = domain_xml_root.find("devices")

    disk_map = {}
    for disk in devices_element.iter("disk"):
        target_id = disk.find("target").get("dev")
        source = disk.find("source")
        vol_desc = DomainVolumeDesc()
        if source.get("file") is not None:
            vol_desc.vol_type = "file"
            pure_path = PurePosixPath(source.get("file"))
            vol_desc.vol_path = pure_path.parent
            vol_desc.vol_name = pure_path.name
        elif source.get("pool") is not None:
            vol_desc.vol_type = "pool"
            vol_desc.vol_pool = source.get("pool")
            vol_desc.vol_name = source.get("volume")
        disk_map[target_id] = vol_desc
    
    return disk_map

def removeVolumesAlreadyMigrated(volumes: dict[str, DomainVolumeDesc], pool: str = None, filepath: str = None) -> dict[str, DomainVolumeDesc]:
    if filepath is None == pool is None:
        raise Exception("Must specify EITHER pool or filepath, but not both.")

    devs_to_remove = []
    migrated_volumes = {}
    for target_dev, volume_description in volumes.items():
        if filepath is not None:
            if volume_description.vol_type == "file" and PurePosixPath(volume_description.vol_path) == PurePosixPath(filepath):
                devs_to_remove.append(target_dev)
        else:
            if volume_description.vol_type == "pool" and volume_description.vol_pool == pool:
                devs_to_remove.append(target_dev)
    
    for target_dev in devs_to_remove:
        migrated_volumes[target_dev] = volumes.pop(target_dev)

    return migrated_volumes


def getDestinationXML(volume_description: DomainVolumeDesc, pool: str = None, filepath: str = None) -> str:
    if filepath is None == pool is None:
        raise Exception("Must specify EITHER pool OR filepath, but not both.")
    
    if filepath is not None:
        dest_xml = "<disk type='file' device='disk'>"
    else:
        dest_xml = "<disk type='volume' device='disk'>"
    dest_xml += "<driver name='qemu' type='qcow2'/>"
    if filepath is not None:
        dest_xml += f"<source file='{filepath}/{volume_description.vol_name}'/>"
    else:
        dest_xml += f"<source pool='{pool}' volume='{volume_description.vol_name}'/>"
    dest_xml += "</disk>"

    return dest_xml

def checkForOngoingBlockCopy(domain: libvirt.virDomain, target_devs: list[str]) -> list[str]:
    devs_with_jobs = []
    for target_dev in target_devs:
        if len(domain.blockJobInfo(target_dev)):
            devs_with_jobs.append(target_dev) 
    return devs_with_jobs


def waitForBlockCopy(domain: libvirt.virDomain, target_dev: str):
    while True:
        job_status = domain.blockJobInfo(target_dev)
        if "cur" in job_status and job_status['cur'] < job_status['end']:
            progress = 100 * job_status['cur'] // job_status['end']
            print(f"\rMigrating {target_dev} -- {progress}%", end="")
            time.sleep(1)
        else:
            print(f"\rMigrating {target_dev} -- 100%", end="")
            break
    print()

def waitForAllBlockCopy(domain: libvirt.virDomain, target_devs: list):
    devs_complete = set()
    while len(devs_complete) < len(target_devs):
        print("\r", end="")
        for target_dev in target_devs:
            if target_dev in devs_complete:
                print(f"Migrating {target_dev} -- 100%\t", end="")
            else:
                job_status = domain.blockJobInfo(target_dev)
                if "cur" in job_status and job_status['cur'] < job_status['end']:
                    progress = 100 * job_status['cur'] // job_status['end']
                    print(f"Migrating {target_dev} -- {progress}%\t", end="")
                else:
                    print(f"Migrating {target_dev} -- 100%\t", end="")
                    devs_complete.add(target_dev)
        time.sleep(1)
    print()

def pivotAllBlockCopyJobs(domain: libvirt.virDomain, target_devs: list):
    for target_dev in target_devs:
        domain.blockJobAbort(target_dev, 0 | libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT)

def printParsedInfo(domain: str, volumes: dict[str, DomainVolumeDesc], migrated_volumes: dict[str, DomainVolumeDesc], pool: str, filepath: str):
    print(f"\nWhat will happen:\n{SEPARATOR}\n")
    print(f"Domain name:\n{SEPARATOR}\n{domain}\n{SEPARATOR}\n")
    print(f"Volumes:")
    printVolumesAndDestinations(volumes, pool, filepath)
    if migrated_volumes is not None and len(migrated_volumes): 
        print("\nVolumes already migrated:")
        printVolumesAndDestinations(migrated_volumes, pool, filepath)


def printVolumesAndDestinations(disk_map: dict[str, DomainVolumeDesc], pool: str, filepath: str):
    if filepath is None == pool is None:
        raise Exception("Must specify EITHER pool OR filepath, but not both.")

    print(SEPARATOR)
    for target_id, disk_desc in disk_map.items():
        print(f"Target dev: {target_id}")
        if disk_desc.vol_type == "file":
            print(f"File path: {disk_desc.vol_path}/{disk_desc.vol_name}")
        elif disk_desc.vol_type == "pool":
            print(f"Volume Pool: {disk_desc.vol_pool} -- Volume Name: {disk_desc.vol_name}")   
        
        if filepath is not None:
            print(f"Destination file path: {filepath}/{disk_desc.vol_name}")
        else:
            print(f"Destination pool: {pool}")
        print(f"Destination XML: {getDestinationXML(disk_desc, pool, filepath)}")
        print(SEPARATOR)

        
def printLibvirtErrorAndExit(error: libvirt.libvirtError):
    print(f"Error code: {error.get_error_code()}")
    print(f"Error message: {error.get_error_message()}")
    exit(1)
    

if __name__ == "__main__":
    main()