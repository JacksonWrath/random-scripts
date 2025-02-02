#!/usr/bin/python3

import os
import sys


def main():
    args = sys.argv
    if len(args) != 2:
        print("One argument expected, the destination folder path")
        sys.exit(1)

    destPath = args[1]
    print(f"Creating destination: {destPath}")
    os.makedirs(destPath, exist_ok=True)
    workingDir = os.curdir
    for currentdir, dirnames, filenames in os.walk(workingDir):
        currentdir = currentdir.lstrip("./")
        newdir = os.path.join(destPath, currentdir)
        for file in sorted(filenames):
            src = os.path.join(currentdir, file)
            dst = os.path.join(newdir, file)
            print(f'Hard linking "{src}" to "{dst}"')
            os.link(src=os.path.join(currentdir, file), dst=os.path.join(newdir, file))
        for dir in sorted(dirnames):
            dirpath = os.path.join(newdir, dir)
            print(f"Creating dir: {dirpath}")
            os.makedirs(os.path.join(newdir, dir))


if __name__ == "__main__":
    main()
