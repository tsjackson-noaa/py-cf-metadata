import os
import sys
import io
import collections
import errno
import json
import subprocess

def git_info(repo_dir=None):
    """Get the current git branch, hash, and list of uncommitted files, if 
    available. Based on NumPy's implementation: 
    `https://stackoverflow.com/a/40170206`__.
    """
    def _minimal_cmd(cmd):
        # construct minimal environment
        env = {'LANGUAGE':'C', 'LANG':'C', 'LC_ALL':'C'}
        for k in ['SYSTEMROOT', 'PATH']:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v
        try:
            out = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, 
                env=env, cwd=repo_dir
            ).communicate()[0]
        except subprocess.CalledProcessError:
            out = ''
        return out.strip().decode('utf-8')

    git_branch = ""
    git_hash = ""
    git_dirty = ""
    try:
        git_branch = _minimal_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        git_hash = _minimal_cmd(['git', 'rev-parse', 'HEAD'])
        git_dirty = _minimal_cmd(['git', 'diff', '--no-ext-diff', '--name-only'])
    except OSError:
        pass
        
    if not git_hash:
        git_hash = "<couldn't get git hash>"
    if not git_branch:
        git_branch = "<couldn't get git branch>"
    if git_dirty:
        git_branch = git_branch + " (with uncommitted changes)"
    return (git_hash, git_branch)

def strip_comments(str_, delimiter=None):
    # would be better to use shlex, but that doesn't support multi-character
    # comment delimiters like '//'
    if not delimiter:
        return str_
    s = str_.splitlines()
    for i in list(range(len(s))):
        if s[i].startswith(delimiter):
            s[i] = ''
            continue
        # If delimiter appears quoted in a string, don't want to treat it as
        # a comment. So for each occurrence of delimiter, count number of 
        # "s to its left and only truncate when that's an even number.
        # TODO: handle ' as well as ", for non-JSON applications
        s_parts = s[i].split(delimiter)
        s_counts = [ss.count('"') for ss in s_parts]
        j = 1
        while sum(s_counts[:j]) % 2 != 0:
            j += 1
        s[i] = delimiter.join(s_parts[:j])
    # join lines, stripping blank lines
    return '\n'.join([ss for ss in s if (ss and not ss.isspace())])

def read_json(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), file_path)
    try:    
        with io.open(file_path, 'r', encoding='utf-8') as file_:
            str_ = file_.read()
    except IOError:
        sys.exit(f'Fatal IOError when reading {file_path}. Exiting.')
    try:
        str_ = parse_json(str_)
    except (UnicodeDecodeError, json.decoder.JSONDecodeError):
        sys.exit(f'JSON formatting error in file {file_path}')
    return str_

def parse_json(str_):
    str_ = strip_comments(str_, delimiter= '//') # JSONC quasi-standard
    try:
        parsed_json = json.loads(str_, object_pairs_hook=collections.OrderedDict)
    except UnicodeDecodeError:
        print('Unicode error while decoding JSON.')
        raise
    except json.decoder.JSONDecodeError:
        print('JSON formatting error.')
        raise
    return parsed_json

def write_json(struct, file_path, **kwargs):
    kwargs.setdefault('sort_keys', False)
    kwargs.setdefault('indent', 2)
    kwargs.setdefault('separators', (',', ': '))
    encoding = kwargs.pop('encoding', 'utf-8')
    if kwargs.get('ensure_ascii', False):
        encoding='ascii'
    try:
        if os.path.exists(file_path):
            print(f'Overwriting {file_path}')
        with open(file_path, 'w', encoding=encoding, errors='strict') as file_:
            json.dump(struct, file_, **kwargs)
    except IOError:
        sys.exit(f'Fatal IOError when trying to write {file_path}.')
