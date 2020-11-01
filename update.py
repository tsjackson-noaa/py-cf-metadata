#!/usr/bin/env python
"""Script to parse XML files of CF convention terminology from a local checkout
of `https://github.com/cf-convention/cf-convention.github.io`__ and output the
information into the more compact JSON format in /tables.
"""

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
import datetime
import json
import warnings
import py_cf_metadata as cf

def provenance_dict(repo_dir, upstream_repo_dir):
    """Obtain provenance info (modification date and git commit) to include in
    metadata for output JSON files.
    """
    now_ = datetime.datetime.now(tz=datetime.timezone.utc)
    my_hash, my_branch = cf.git_info(repo_dir)
    up_hash, up_branch = cf.git_info(upstream_repo_dir)
    return {
        'last_modified': now_.isoformat(),
        'tsjackson-noaa/cf-convention-data': {
            'hash': my_hash, 'branch': my_branch
        },
        'cf-convention/cf-convention.github.io': {
            'hash': up_hash, 'branch': up_branch
        }
    }

def output_table(dir_, category_name, xml_proc, prov_d):
    path = os.path.join(dir_, category_name+'.json')
    prov_copy = prov_d.copy()
    prov_copy['current_revision'] = str(xml_proc.max_version)
    prov_copy['dataclass'] = xml_proc.DataClass.__name__
    out_d = {
        'provenance': prov_copy,
        'revision_dates': xml_proc.rev_dates.to_struct(),
        category_name: {k: v.to_struct() \
            for k, v in xml_proc.rev_history_d.items() if v is not None}
    }
    cf.write_json(out_d, path, sort_keys=False, indent=2, ensure_ascii=True)

# --------------------------------------------------------------

def main(my_repo_dir, cf_repo_dir):
    out_dir = os.path.join(my_repo_dir, 'tables')
    os.makedirs(out_dir, exist_ok=True)
    prov_d = provenance_dict(my_repo_dir, cf_repo_dir)

    std_name_dir = os.path.join(cf_repo_dir, 'Data', 'cf-standard-names')
    std_name_proc = cf.StdNameXMLProcessor(std_name_dir, cf.StandardName)
    std_name_proc.process()
    output_table(out_dir, 'cf-standard-names', std_name_proc, prov_d)

    std_name_proc = cf.StdNameXMLProcessor(std_name_dir, cf.StandardNameAlias)
    std_name_proc.process()
    output_table(out_dir, 'cf-standard-name-aliases', std_name_proc, prov_d)

    std_name_proc = cf.StdNameXMLProcessor(std_name_dir, cf.StandardNameAliasAMIP)
    std_name_proc.process()
    output_table(out_dir, 'cf-standard-name-aliases-amip', std_name_proc, prov_d)

    std_name_proc = cf.StdNameXMLProcessor(std_name_dir, cf.StandardNameAliasGRIB)
    std_name_proc.process()
    output_table(out_dir, 'cf-standard-name-aliases-grib', std_name_proc, prov_d)

    area_type_dir = os.path.join(cf_repo_dir, 'Data', 'area-type-table')
    area_type_proc = cf.AreaTypeXMLProcessor(area_type_dir, cf.AreaType)
    area_type_proc.process()
    output_table(out_dir, 'area-type-table', area_type_proc, prov_d)

    std_region_dir = os.path.join(cf_repo_dir, 'Data', 'standardized-region-list')
    std_region_proc = cf.StdRegionXMLProcessor(std_region_dir, cf.StandardizedRegion)
    std_region_proc.process()
    output_table(out_dir, 'standardized-region-list', std_region_proc, prov_d)

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
