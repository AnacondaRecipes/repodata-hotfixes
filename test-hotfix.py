import json
import os
import difflib
import subprocess

from six.moves import urllib
from conda.exports import subdir
from conda_build.index import _apply_instructions

html_differ = difflib.HtmlDiff()
diff_options = {'unified': difflib.unified_diff,
                'context': difflib.context_diff,
                'html': html_differ.make_file}
diff_context_keyword = {'unified': 'n',
                        'context': 'n',
                        'html': 'numlines'}

channel_map = {
    'main': 'https://repo.anaconda.com/pkgs/main',
    'free': 'https://repo.anaconda.com/pkgs/free',
    'r': 'https://repo.anaconda.com/pkgs/r',
}


def clone_subdir(channel_base_url, subdir):
    out_file = os.path.join(channel_base_url.rsplit('/', 1)[-1], subdir, 'reference_repodata.json')
    url = "%s/%s/repodata.json" % (channel_base_url, subdir)
    print("downloading repodata from {}".format(url))
    urllib.request.urlretrieve(url, out_file)

    out_file = os.path.join(channel_base_url.rsplit('/', 1)[-1], subdir, 'repodata_from_packages.json')
    url = "%s/%s/repodata_from_packages.json" % (channel_base_url, subdir)
    print("downloading repodata from {}".format(url))
    urllib.request.urlretrieve(url, out_file)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('channel', help='channel name or url to download repodata from')
    parser.add_argument('--subdir', help='subdir to download/diff', default=subdir)
    parser.add_argument('--diff-format', help='format to save diff as',
                        choices=('unified', 'context', 'html'), default='html')
    parser.add_argument('--context-numlines', help='context lines to show around diff',
                        type=int, default=5)
    args = parser.parse_args()

    if not os.path.isdir(os.path.join(args.channel, args.subdir)):
        os.makedirs(os.path.join(args.channel, args.subdir))
    if '/' not in args.channel:
        channel_base_url = channel_map[args.channel]
    clone_subdir(channel_base_url, args.subdir)
    subprocess.check_call(['python', args.channel + '.py'])
    raw_repodata_file = os.path.join(args.channel, args.subdir, 'repodata_from_packages.json')
    ref_repodata_file = os.path.join(args.channel, args.subdir, 'reference_repodata.json')
    with open(raw_repodata_file) as f:
        repodata = json.load(f)
    out_instructions = os.path.join(args.channel, args.subdir, 'patch_instructions.json')
    with open(out_instructions) as f:
        instructions = json.load(f)
    patched_repodata = _apply_instructions(args.subdir, repodata, instructions)
    patched_repodata_file = os.path.join(args.channel, args.subdir, 'repodata-patched.json')
    with open(patched_repodata_file, 'w') as f:
        json.dump(patched_repodata, f, indent=2, sort_keys=True, separators=(',', ': '))
    subprocess.call(['colordiff', ref_repodata_file, patched_repodata_file])
