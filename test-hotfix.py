import difflib
import json
import os
import subprocess

from conda.exports import subdir as conda_subdir
from conda_index.index import _apply_instructions
import urllib

html_differ = difflib.HtmlDiff()
diff_options = {'unified': difflib.unified_diff,
                'context': difflib.context_diff,
                'html': html_differ.make_file}
diff_context_keyword = {'unified': 'n',
                        'context': 'n',
                        'html': 'numlines'}

channel_map = {
    "main": "https://repo.anaconda.com/pkgs/main",
    "r": "https://repo.anaconda.com/pkgs/r",
    "msys2": "https://repo.anaconda.com/pkgs/msys2",
    "numpy2": "https://anaconda.org/ad-testing/numpy",
}


def clone_subdir(channel_base_url: str, subdir: str):
    """Download repodata.json and repodata_from_packages.json from channel

    Args:
        channel_base_url (str):
        subdir (str): subdir of channel (aka platform) to download
    """
    out_file = os.path.join(channel_base_url.rsplit('/', 1)[-1], subdir, 'repodata-reference.json')
    url = "%s/%s/repodata.json" % (channel_base_url, subdir)
    print("downloading repodata from {}".format(url))
    urllib.request.urlretrieve(url, out_file)

    out_file = os.path.join(channel_base_url.rsplit('/', 1)[-1], subdir, 'repodata_from_packages.json')
    url = "%s/%s/repodata_from_packages.json" % (channel_base_url, subdir)
    print("downloading repodata from {}".format(url))
    urllib.request.urlretrieve(url, out_file)


def show_pkgs(subdir, ref_repodata_file, patched_repodata_file):
    with open(ref_repodata_file) as f:
        reference_repodata = json.load(f)
    with open(patched_repodata_file) as f:
        patched_repodata = json.load(f)
    for name, ref_pkg in reference_repodata["packages"].items():
        new_pkg = patched_repodata["packages"][name]
        if ref_pkg == new_pkg:
            continue
        print(f"{subdir}::{name}")
        ref_lines = json.dumps(ref_pkg, indent=2).splitlines()
        new_lines = json.dumps(new_pkg, indent=2).splitlines()
        for line in difflib.unified_diff(ref_lines, new_lines, n=0, lineterm=''):
            if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
                continue
            print(line)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Test new hotfix changes before they are deployed.')
    parser.add_argument('channel', help='channel name or url to download repodata from')
    parser.add_argument('--subdirs', nargs='*', help='subdir(s) to download/diff', default=(conda_subdir, ))
    parser.add_argument('--diff-format', help='format to save diff as',
                        choices=('unified', 'context', 'html'), default='html')
    parser.add_argument('--context-numlines', help='context lines to show around diff',
                        type=int, default=5)
    parser.add_argument('--use-cache', action='store_true', help='use cached repodata')
    parser.add_argument('--color', action='store_true', help='use colordiff rather than diff')
    parser.add_argument('--show-pkgs', action='store_true', help='Show packages that differ')
    args = parser.parse_args()

    print(f"Creating channel directory structure for channel '{args.channel}' and platforms {args.subdirs}")
    for subdir in args.subdirs:
        if not os.path.isdir(os.path.join(args.channel, subdir)):
            os.makedirs(os.path.join(args.channel, subdir))

    # NOTE: Not sure why this is checked (only main, r and msys2 are available)
    # This is the only place where channel_base_url is set.
    if '/' not in args.channel:
        channel_base_url = channel_map[args.channel]
        print(f"Applying url to alias {args.channel}. {channel_base_url=}")

    if args.use_cache:
        print(f"Using cache for {' '.join(args.subdirs)}.")
    if not args.use_cache:
        print(f"Cloning subdirs {' '.join(args.subdirs)}...")
        for subdir in args.subdirs:
            clone_subdir(channel_base_url, subdir)

    print(f"Executing hotfix for channel '{args.channel}'.")
    subprocess.check_call(['python', args.channel + '.py'])
    print(f"Completed hotfix for channel '{args.channel}'.")

    print("Analyzing results...")
    for subdir in args.subdirs:
        raw_repodata_file = os.path.join(args.channel, subdir, 'repodata_from_packages.json')
        with open(raw_repodata_file) as f:
            repodata = json.load(f)
        out_instructions = os.path.join(args.channel, subdir, 'patch_instructions.json')
        with open(out_instructions) as f:
            instructions = json.load(f)
        patched_repodata = _apply_instructions(subdir, repodata, instructions)
        patched_repodata_file = os.path.join(args.channel, subdir, 'repodata-patched.json')
        print(f"Writing out new repodata as {patched_repodata_file} for '{subdir}' platform.")
        with open(patched_repodata_file, 'w') as f:
            json.dump(patched_repodata, f, indent=2, sort_keys=True, separators=(',', ': '))
            f.write('\n')

        ref_repodata_file = os.path.join(args.channel, subdir, 'repodata-reference.json')
        if args.show_pkgs:
            print("New Hot Fixes:")
            show_pkgs(subdir, ref_repodata_file, patched_repodata_file)
        else:
            if args.color:
                diff_exe = 'colordiff'
            else:
                diff_exe = 'diff'
            fmt_flag = '{} {}'.format(
                '-U' if args.diff_format == 'unified' else '-C',
                args.context_numlines,
                )
            subprocess.call([diff_exe, fmt_flag, ref_repodata_file, patched_repodata_file])
