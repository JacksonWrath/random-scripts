#!/usr/bin/python3

import filecmp
import os
import sys

from termcolor import colored

SHALLOW = False


def main():
    srcPathOne = sys.argv[1]
    srcPathTwo = sys.argv[2]

    dcmp = filecmp.dircmp(srcPathOne, srcPathTwo, shallow=SHALLOW)

    if print_diff_files(dcmp):
        print("Folders are identical.")
    else:
        print("Something didn't match. Check output.")


def print_diff_files(dcmp):
    identical = not len(dcmp.left_only) and not len(dcmp.right_only)
    print(f"{dcmp.right}", end="\r")

    files_different = []
    for index, file in enumerate(dcmp.common_files):
        progress = f"{index}/{len(dcmp.common_files)}"
        current_status = f"{progress} - {dcmp.right}/{file}"
        padding = " " * max(0, os.get_terminal_size().columns - len(current_status))
        print(f"{current_status}{padding}", end="\r")
        if not filecmp.cmp(f"{dcmp.left}/{file}", f"{dcmp.right}/{file}", shallow=SHALLOW):
            identical = False
            files_different.append(f"{dcmp.right}/{file}")

    diff_details = ""
    if identical:
        current_status = f"{dcmp.right} {colored("✔", "green")}"
    else:
        current_status = f"{dcmp.right} {colored("✘", "red")}"
        if len(dcmp.left_only):
            diff_details += f"\nOnly in {dcmp.left}:\n{dcmp.left_only}"
        if len(dcmp.right_only):
            diff_details += f"\nOnly in {dcmp.right}:\n{dcmp.right_only}"
        if len(files_different):
            diff_details += f"\nFiles different: {files_different}"

    padding = " " * max(0, os.get_terminal_size().columns - len(current_status))
    print(f"{current_status}{padding}{diff_details}")

    for sub_dcmp in dcmp.subdirs.values():
        identical = print_diff_files(sub_dcmp) and identical

    return identical


if __name__ == "__main__":
    main()
