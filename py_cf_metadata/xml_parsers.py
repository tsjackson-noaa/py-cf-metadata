import os
import abc
import glob
import warnings
import xml.etree.ElementTree as ET

from .classdefs import (
    _CURRENT_V, _UNINIT_V,
    RevisionHistoryWrapper, RevisionDateList
)

class XMLProcessor(abc.ABC):
    """Base class for reading and parsing XMLs from the cf-convention.github.io
    repo. Entries in the XML are parsed into versioned instances of the
    ``DataClass`` class.
    """
    dict_factory = dict

    def __init__(self, xml_dir, DataClass):
        self.xml_dir = xml_dir
        self.DataClass = DataClass
        self.rev_history_d = self.dict_factory()
        self.rev_dates = RevisionDateList()
        self.max_version = _UNINIT_V

    @abc.abstractmethod
    def xml_path(self, version_str):
        """Abstract method. Returns the subdirectory in the cf-convention.github.io
        repo where the XMLs defining the child class' type of data are stored.
        """
        pass

    def get_versions(self, path):
        """Obtain list of CF standard revision numbers from XML files in ``path``.
        """
        with os.scandir(path) as iter_:
            version_dirs = [d.name for d in iter_ if \
                d.is_dir() and not (d.name.startswith('.') or d.name == 'docs')]
        return self.v_cleanup(version_dirs)

    @staticmethod
    def v_cleanup(version_strs):
        """Munge list of CF standard revision numbers gathered from XML file 
        names.
        """
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
            _, _, el.tag = el.tag.rpartition('}') # strip namespaces
            for at in el.attrib: # strip namespaces of attributes too
                if '}' in at:
                    newat = at.split('}', 1)[1]
                    el.attrib[newat] = el.attrib[at]
                    del el.attrib[at]
        return it.root

    def dict_update(self, update_d, update_version):
        """Update internal data (a dict of 
        :class:`~classdefs.RevisionHistoryWrapper` objects) with changes from 
        the revision of the CF standard we just read. Entries that were dropped 
        have their ``end_revision`` attribute set; new entries have new objects
        created.
        """
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
                warnings.warn(
                    'Multiple assignments to {} in version {}\nCurrent: {}\nNew: {}'.format(
                        k, update_version, 
                        self.rev_history_d[k].to_struct(), update_d[k].to_struct()))
            self.rev_history_d[k] = \
                RevisionHistoryWrapper.from_obj(update_d[k], update_version)
            # print("\tAdd: {} ({})\nCurrent: {}\nNew: {}".format(
            #     k, update_version, self.rev_history_d[k], update_d[k]))

    def process(self):
        """Read and parse all XML files (ie all revision numbers).
        """
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
    """:class:`XMLProcessor` for parsing CF standard names and standard name 
    aliases.
    """
    def xml_path(self, v_str):
        return os.path.join(
            self.xml_dir, v_str, 'src', 'cf-standard-name-table.xml'
        )

class AreaTypeXMLProcessor(XMLProcessor):
    """:class:`XMLProcessor` for parsing CF area types.
    """
    def xml_path(self, v_str):
        return os.path.join(
            self.xml_dir, v_str, 'src', 'area-type-table.xml'
        )

class StdRegionXMLProcessor(XMLProcessor):
    """:class:`XMLProcessor` for parsing CF standard regions.
    """
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