#!/usr/bin/env python

import sys
# do version check before importing other stuff
if sys.version_info[0] != 3 or sys.version_info[1] < 7:
    print(("ERROR: Update script only supports python >= 3.7. Please check "
    "which version is on your $PATH (e.g. with `which python`.)"))
    print("Attempted to run with following python version:\n{}".format(sys.version))
    exit()
# passed; continue with imports
import os
import argparse
import abc
import datetime
import glob
import json
import subprocess
import warnings
import xml.etree.ElementTree as ET

from py_cf_metadata.classdefs import (
    _CURRENT_V, _UNINIT_V
    StandardName, AreaType, StandardizedRegion,
    StandardNameAlias, StandardNameAliasAMIP, StandardNameAliasGRIB,
    RevisionHistoryWrapper,
    RevisionDateList
)

class XMLProcessor(abc.ABC):
    dict_factory = dict

    def __init__(self, xml_dir, DataClass):
        self.xml_dir = xml_dir
        self.DataClass = DataClass
        self.rev_history_d = self.dict_factory()
        self.rev_dates = RevisionDateList()
        self.max_version = _UNINIT_V

    @abc.abstractmethod
    def xml_path(self, version_str):
        pass

    def get_versions(self, path):
        with os.scandir(path) as iter_:
            version_dirs = [d.name for d in iter_ if \
                d.is_dir() and not (d.name.startswith('.') or d.name == 'docs')]
        return self.v_cleanup(version_dirs)

    @staticmethod
    def v_cleanup(version_strs):
        assert 'current' in version_strs
        version_strs.remove('current')
        version_ints = sorted([int(d) for d in version_strs])
        max_version = max(version_ints)
        version_strs = [str(d) for d in version_ints] + ['current']
        return (version_strs, max_version)

    @staticmethod
    def strip_namespaces(file_):
        """Load an XML file and strip namespace information (to simplify parsing.)
        Taken from `https://stackoverflow.com/a/25920989`__.
        """
        it = ET.iterparse(file_)
        for _, el in it:
            for _, el in it:
                _, _, el.tag = el.tag.rpartition('}') # strip namespaces
            for at in el.attrib: # strip namespaces of attributes too
                if '}' in at:
                    newat = at.split('}', 1)[1]
                    el.attrib[newat] = el.attrib[at]
                    del el.attrib[at]
        return it.root

    def dict_update(self, update_d, update_version):
        d_keys = set(self.rev_history_d.keys())
        update_keys = set(update_d.keys())
        for k in d_keys.intersection(update_keys):
            # update entries in both ref_d and update_d: update only the fields
            # that we've decided to update.
            try:
                self.rev_history_d[k].update(update_d[k], update_version)
            except ValueError as exc:
                print(exc)
                continue
            #print("\tUpdate: ",k, update_d[k].version_added, ref_d[k].version_added)
        for k in d_keys.difference(update_keys):
            # entries in ref_d that aren't in update_d: 
            self.rev_history_d[k].end_revision(update_version)
        for k in update_keys.difference(d_keys):
            # entries in update_d not in ref_d : add them.
            if update_version == _CURRENT_V:
                # data in "current" should be a duplicate of most current 
                # numbered version, so shouldn't be adding anything then
                warnings.warn("Modifications made to {} in 'current'".format(k))
            if k in self.rev_history_d and self.rev_history_d[k] != update_d[k]:
                # if we already added this entry, that's a problem
                #raise KeyError(
                warnings.warn(
                    'Multiple assignments to {} in version {}\nCurrent: {}\nNew: {}'.format(
                        k, update_version, 
                        self.rev_history_d[k].to_struct(), update_d[k].to_struct()))
            self.rev_history_d[k] = \
                RevisionHistoryWrapper.from_obj(update_d[k], update_version)
            # print("\tAdd: {} ({})\nCurrent: {}\nNew: {}".format(
            #     k, update_version, self.rev_history_d[k], update_d[k]))

    def process(self):
        v_strs, self.max_version = self.get_versions(self.xml_dir)
        for v_str in v_strs:
            v_int = (_CURRENT_V if v_str == 'current' else int(v_str))
            print(v_str, end=" ")
            xml_path = self.xml_path(v_str)
            assert os.path.exists(xml_path)
            root = self.strip_namespaces(xml_path)
            self.rev_dates.add_modified_date_from_xml(root, v_str)
            
            update_d = dict()
            for x in root.iterfind(self.DataClass.xml_tag):
                k = self.DataClass.key_from_xml(x)
                val = self.DataClass.val_from_xml(x)
                if k in update_d and update_d[k] != val:
                    #raise KeyError(
                    warnings.warn(
                        'Multiple assignments to {} in file {}\nCurrent: {}\nNew: {}'.format(
                            k, v_str, update_d[k].to_struct(), val.to_struct()))
                update_d[k] = val
            self.dict_update(update_d, v_int)
        print()

        # remove completely empty entries
        for val in self.rev_history_d.values():
            val.remove_empty_revisions()
        self.rev_history_d = {k:v for k,v in self.rev_history_d.items() \
            if not v.is_empty()}

        # sort by keys; all dicts in py3.7+ are OrderedDicts
        self.rev_history_d = dict(sorted(self.rev_history_d.items()))

class StdNameXMLProcessor(XMLProcessor):
    def xml_path(self, v_str):
        return os.path.join(
            self.xml_dir, v_str, 'src', 'cf-standard-name-table.xml'
        )

class AreaTypeXMLProcessor(XMLProcessor):
    def xml_path(self, v_str):
        return os.path.join(
            self.xml_dir, v_str, 'src', 'area-type-table.xml'
        )

class StdRegionXMLProcessor(XMLProcessor):
    def get_versions(self, path):
        glob_ = 'standardized-region-list.*.xml'
        files = glob.glob(os.path.join(path, glob_))
        v_strs = [os.path.basename(f).split('.')[1] for f in files]
        return self.v_cleanup(v_strs)

    def xml_path(self, v_str):
        return os.path.join(
            self.xml_dir, 'standardized-region-list.'+v_str+'.xml'
        )

# --------------------------------------------------------------

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

def provenance_dict(repo_dir, upstream_repo_dir):
    now_ = datetime.datetime.now(tz=datetime.timezone.utc)
    my_hash, my_branch = git_info(repo_dir)
    up_hash, up_branch = git_info(upstream_repo_dir)
    return {
        'last_modified': now_.isoformat(),
        'tsjackson-noaa/cf-convention-data': {
            'hash': my_hash, 'branch': my_branch
        },
        'cf-convention/cf-convention.github.io': {
            'hash': up_hash, 'branch': up_branch
        }
    }

def write_json(dir_, category_name, xml_proc, prov_d):
    path = os.path.join(dir_, category_name+'.json')
    if os.path.exists(path):
        print('Overwriting {}'.format(path))
    prov_copy = prov_d.copy()
    prov_copy['current_revision'] = str(xml_proc.max_version)
    prov_copy['dataclass'] = xml_proc.DataClass.__name__
    out_d = {
        'provenance': prov_copy,
        'revision_dates': xml_proc.rev_dates.to_struct(),
        category_name: {k: v.to_struct() \
            for k, v in xml_proc.rev_history_d.items() if v is not None}
    }
    with open(path, 'w') as f:
        json.dump(out_d, f, sort_keys=False, indent=2, ensure_ascii=True)

# --------------------------------------------------------------

def main(my_repo_dir, cf_repo_dir):
    out_dir = os.path.join(my_repo_dir, 'tables')
    os.makedirs(out_dir, exist_ok=True)
    prov_d = provenance_dict(my_repo_dir, cf_repo_dir)

    std_name_dir = os.path.join(cf_repo_dir, 'Data', 'cf-standard-names')
    std_name_proc = StdNameXMLProcessor(std_name_dir, StandardName)
    std_name_proc.process()
    write_json(out_dir, 'cf-standard-names', std_name_proc, prov_d)

    std_name_proc = StdNameXMLProcessor(std_name_dir, StandardNameAlias)
    std_name_proc.process()
    write_json(out_dir, 'cf-standard-name-aliases', std_name_proc, prov_d)

    std_name_proc = StdNameXMLProcessor(std_name_dir, StandardNameAliasAMIP)
    std_name_proc.process()
    write_json(out_dir, 'cf-standard-name-aliases-amip', std_name_proc, prov_d)

    std_name_proc = StdNameXMLProcessor(std_name_dir, StandardNameAliasGRIB)
    std_name_proc.process()
    write_json(out_dir, 'cf-standard-name-aliases-grib', std_name_proc, prov_d)

    area_type_dir = os.path.join(cf_repo_dir, 'Data', 'area-type-table')
    area_type_proc = AreaTypeXMLProcessor(area_type_dir, AreaType)
    area_type_proc.process()
    write_json(out_dir, 'area-type-table', area_type_proc, prov_d)

    std_region_dir = os.path.join(cf_repo_dir, 'Data', 'standardized-region-list')
    std_region_proc = StdRegionXMLProcessor(std_region_dir, StandardizedRegion)
    std_region_proc.process()
    write_json(out_dir, 'standardized-region-list', std_region_proc, prov_d)

# --------------------------------------------------------------

if __name__ == '__main__':
    # Wrap input/output if we're called as a standalone script
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true",
        help="increase output verbosity")
    parser.add_argument("cf_repo_dir", 
        help="Path to the local checkout of cf-convention/cf-convention.github.io.")
    args = parser.parse_args()

    my_repo_dir = os.path.dirname(os.path.realpath(__file__))
    cf_repo_dir = args.cf_repo_dir
    assert os.path.exists(cf_repo_dir)

    main(my_repo_dir, cf_repo_dir)
