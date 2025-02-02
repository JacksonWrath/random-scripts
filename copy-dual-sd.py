#!/usr/bin/python3

# My camera supports mirroring to 2 SD cards, so I wrote this script for some sanity checks:
#  - validate that the files on the SD cards are the same
#  - validate that the copied files didn't get garbled in-transit
# It also copies from both SD cards at once, to speed up the copy a bit.


import filecmp
import os
import queue
import shutil
import sys
import threading

import psutil
from termcolor import colored

SHALLOW = False

COMMON_ROOT = "DCIM"

FILE_QUEUE = queue.Queue()
PROGRESS_SEMAPHORE = threading.Semaphore()


def main():
    # Find the mount points for the provided devs
    dev1 = f"/dev/{sys.argv[1]}"
    dev2 = f"/dev/{sys.argv[2]}"

    mounts = psutil.disk_partitions()
    mount1 = None
    mount2 = None
    for mount in mounts:
        if mount.device == dev1:
            mount1 = mount.mountpoint
        if mount.device == dev2:
            mount2 = mount.mountpoint

    if mount1 is None or mount2 is None:
        print(f"Mountpoints not found for devices ({dev1}, {dev2}). Found mounts:")
        print(mounts)
        print("Aborting.")
        sys.exit(1)

    print(f"Found {dev1} mount: {mount1}")
    print(f"Found {dev2} mount: {mount2}")

    srcPathOne = f"{mount1}/{COMMON_ROOT}"
    srcPathTwo = f"{mount2}/{COMMON_ROOT}"

    print("Checking files in sources are identical...")
    dcmp = filecmp.dircmp(srcPathOne, srcPathTwo, shallow=SHALLOW)

    if not compare_dirs(dcmp):
        print("Differences found in sources. Aborting.")
        sys.exit(1)

    destPath = os.getcwd()
    print(f"Copying to {destPath}...")

    threading.Thread(target=copy_worker, name=f"Thread-{dev1}", args=[srcPathOne], daemon=True).start()
    threading.Thread(target=copy_worker, name=f"Thread-{dev2}", args=[srcPathTwo], daemon=True).start()

    # Populate the queue with all files to be copied
    totalCount = 0
    for root, _, files in os.walk(srcPathOne):
        relRoot = root.removeprefix(f"{srcPathOne}").removeprefix("/")
        if not os.path.exists(relRoot) and len(relRoot):
            os.mkdir(relRoot)
        for file in files:
            path = os.path.join(relRoot, file)
            FILE_QUEUE.put_nowait(path)
            totalCount += 1

    # Print progress of copy until done
    while FILE_QUEUE.qsize() != 0:
        PROGRESS_SEMAPHORE.acquire()
        progress = f"Progress: {totalCount - FILE_QUEUE.qsize()}/{totalCount}"
        padding = " " * max(0, os.get_terminal_size().columns - len(progress))
        print(f"{progress}{padding}", end="\r")

    # This print wont overwrite the above progress output completely if copying more than 1 billion files
    # ...you should probably be using something else if that applies to you
    print(f"Comparing copied files with {mount1}...")
    dcmp = filecmp.dircmp(destPath, srcPathOne, shallow=SHALLOW)
    compare_dirs(dcmp)


def compare_dirs(dcmp, shallow=SHALLOW):
    identical = not len(dcmp.left_only) and not len(dcmp.right_only)
    print(f"{dcmp.left}", end="\r")

    filesDifferent = []
    for index, file in enumerate(dcmp.common_files):
        progress = f"{index}/{len(dcmp.common_files)}"
        currentStatus = f"{progress} - {dcmp.left}/{file}"
        padding = " " * max(0, os.get_terminal_size().columns - len(currentStatus))
        print(f"{currentStatus}{padding}", end="\r")
        if not filecmp.cmp(f"{dcmp.left}/{file}", f"{dcmp.left}/{file}", shallow=shallow):
            identical = False
            filesDifferent.append(f"{dcmp.left}/{file}")

    diffDetails = ""
    if identical:
        currentStatus = f"{dcmp.left} {colored("✔", "green")}"
    else:
        currentStatus = f"{dcmp.left} {colored("✘", "red")}"
        if len(dcmp.left_only):
            diffDetails += f"\nOnly in {dcmp.left}:\n{dcmp.left_only}"
        if len(dcmp.right_only):
            diffDetails += f"\nOnly in {dcmp.right}:\n{dcmp.right_only}"
        if len(filesDifferent):
            diffDetails += f"\nFiles different: {filesDifferent}"

    padding = " " * max(0, os.get_terminal_size().columns - len(currentStatus))
    print(f"{currentStatus}{padding}{diffDetails}")

    for sub_dcmp in dcmp.subdirs.values():
        identical = identical and compare_dirs(sub_dcmp)

    return identical


def copy_worker(srcPathRoot):
    try:
        while True:
            file_path = FILE_QUEUE.get()
            srcPath = os.path.join(srcPathRoot, file_path)
            dstPath = os.path.join(os.getcwd(), file_path)
            shutil.copy2(src=srcPath, dst=dstPath)
            FILE_QUEUE.task_done()
            PROGRESS_SEMAPHORE.release()
    except Exception as ex:
        print(ex)


if __name__ == "__main__":
    main()
