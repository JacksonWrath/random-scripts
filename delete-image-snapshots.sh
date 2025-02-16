#!/bin/bash

for i in 5704  6448  7168  7216  7384  7552  7672  7696  7720  7743  7767  7791  7815  7827  7828  7829  7830  7831  7832  7833  7834  7835  7836  7837
do
    sudo btrfs property set /.snapshots/$i/snapshot ro false
    sudo rm /.snapshots/$i/snapshot/var/lib/libvirt/images/win2k19.qcow2
    sudo btrfs property set /.snapshots/$i/snapshot ro true
done