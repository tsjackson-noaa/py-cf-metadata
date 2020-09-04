import bisect
import collections
import collections.abc
import copy
import dataclasses as dc
import datetime
import html
from typing import List
import warnings

# sentinel value for uninitialized/unset version number
_UNINIT_V = -1 
# sentinel value for processing the "current" version: in the cf conventions
# this is always a copy of the highest numbered version, but we still process it
# to verify it's free of errors
_CURRENT_V = 0

class CFBase(object):
    # Tag type in the CF convention tables to use to initialize object instances
    # in the vaf_from_xml() method (defined in child classes.)
    xml_tag = "entry"

    def __post_init__(self):
        """Post-processing of field values.
        """
        for fld in dc.fields(self):
            if fld.type == str:
                # cleanup for all string-valued fields
                key = fld.name
                val = self.__getattribute__(key)
                val = ("" if val is None else val)
                # Convert html-escaped characters (eg. '&quot;') to unicode
                # and strip leading and trailing whitespace
                val = html.unescape(val).strip()
                # replace multiple spaces with single space
                val = ' '.join(val.split())
                self.__setattr__(key, val)

    @classmethod
    def key_from_xml(cls, xml_entry):
        return xml_entry.get('id')

    @classmethod
    def val_from_xml(cls, xml_entry, **kwargs):
        """Initialize dataclass instance from an XML entry (from the CF 
        convention tables.) Field entries not present in the XML can be passed
        as arbitrary kwargs.
        """
        for fld in dc.fields(cls):
            key = fld.name
            if fld.metadata.get('xml_key', ''):
                xml_key = fld.metadata['xml_key']
            else:
                xml_key = key
            # Try to set field's value from an xml tag under this one
            xml_val = xml_entry.find(xml_key)
            if xml_val is not None:
                kwargs[key] = xml_val.text
            else:
                # try to set field's value from this tag's attributes
                xml_val = xml_entry.get(xml_key)
                if xml_val is not None:
                    kwargs[key] = xml_val
        return cls.from_struct(kwargs)

    @classmethod
    def from_struct(cls, d):
        return cls(**d)

    def to_struct(self):
        """Return representation as a dict, eliminating blank entries.
        """
        d = dc.asdict(self)
        return {k:v for k,v in d.items() if v}

    def update(self, other):
        """Update the values of all non-versioned fields (those with compare=
        False) from the values in other.
        """
        assert self.__class__ == other.__class__
        for fld in dc.fields(self):
            key = fld.name
            if fld.compare:
                # raise error when we try to change the value of a versioned
                # field.
                if not self.__getattribute__(key) == other.__getattribute__(key):
                    raise ValueError(
                        "{}: Incompatible update of {}.\nCurrent: {}\nNew: {}".format(
                            self.__class__.__name__, key,
                            dc.asdict(self), dc.asdict(other)
                    ))
            else:
                # just update the field value.
                self.__setattr__(key, other.__getattribute__(key))

    def is_empty(self):
        for fld in dc.fields(self):
            if self.__getattribute__(fld.name):
                return False
        return True


@dc.dataclass
class RevisionHistoryWrapper():
    revisions: list
    revision_start: list
    revision_end: list
    WrappedDataclass: dc.InitVar = None

    @classmethod
    def from_struct(cls, struct):
        obj = cls(revisions=[], revision_start=[], revision_end=[])
        for d in struct:
            start_v = d.pop('revision_start')
            end_v = d.pop('revision_end', _UNINIT_V)
            wrapped_obj = cls.WrappedDataclass.from_struct(d)
            obj.new_revision(wrapped_obj, start_v, end_v)
        return obj

    def to_struct(self):
        def _rev_to_dict(wrapped_obj, start, end):
            d = wrapped_obj.to_struct()
            d['revision_start'] = start
            if end != _UNINIT_V:
                d['revision_end'] = end
            return d

        return [_rev_to_dict(*tup) for tup \
            in zip(self.revisions, self.revision_start, self.revision_end)]

    @classmethod
    def from_obj(cls, wrapped_obj, start_v):
        return cls(
            revisions=[wrapped_obj], 
            revision_start=[start_v], revision_end=[_UNINIT_V],
            WrappedDataclass=wrapped_obj.__class__
        )

    def new_revision(self, new_rev, current_v, end_v=None):
        if len(self.revision_end) > 0 and end_v is None:
            self.end_revision(current_v)
        self.revisions.append(new_rev)
        self.revision_start.append(current_v)
        if end_v is None:
            self.revision_end.append(_UNINIT_V)
        else:
            self.revision_end.append(end_v)

    def end_revision(self, current_v):
        if self.revision_end[-1] == _UNINIT_V:
            self.revision_end[-1] = current_v - 1

    def update(self, x, current_v):
        current_rev = self.revisions[-1]
        current_rev_backup = copy.copy(self.revisions[-1])
        try:
            # try to update our most recent revision to x.
            current_rev.update(x)
        except ValueError:
            # print("update.\nCurrent: {}\nNew: {}".format(
            #     dc.asdict(current_rev_backup), dc.asdict(x)))
            # if we're here, update() threw an exception because x differs 
            # from our current revision in relevant ways (compare==True), 
            # so it should be treated as a new revision.
            self.revisions[-1] = current_rev_backup
            self.new_revision(x, current_v)

    def remove_empty_revisions(self):
        is_empty = [rev.is_empty() for rev in self.revisions]
        self.revisions = [rev for rev, empty \
            in zip(self.revisions, is_empty) if not empty]
        self.revision_start = [v for v, empty \
            in zip(self.revision_start, is_empty) if not empty]
        self.revision_end = [v for v, empty \
            in zip(self.revision_end, is_empty) if not empty]

    def is_empty(self):
        return (len(self.revisions) == 0)

    def filter_by_version(self, version):
        not_current = (self.revision_end[-1] != _UNINIT_V)
        idx = bisect.bisect_right(self.revision_start, version)
        if idx == 0:
            # before earliest revision containing this entry
            return None
        elif idx == len(self.revision_start) \
            and not_current and version > self.revision_end[-1]:
            # after last revision to contain this entry
            return None
        else:
            return self.revisions[idx-1]

    def filter_by_recent(self):
        return self.revisions[-1]

# --------------------------------------------------------------

def warn_on_defaults_factory(field_info, default_value):
    """Returns a function that can be used as a defaults_factory for dataclasses 
    that raises a warning before setting a field to a default value.
    """
    def _dummy_func():
        warnings.warn("No {} recieved, using default {}".format(
            field_info, default_value
        ))
        return default_value
    return _dummy_func

canonical_units_default = warn_on_defaults_factory("StandardName.canonical_units", "1")
@dc.dataclass
class StandardName(CFBase):
    canonical_units: str = dc.field(default_factory=canonical_units_default)
    description: str = dc.field(default="", compare=False)

@dc.dataclass
class AreaType(CFBase):
    description: str = dc.field(default="", compare=False)

@dc.dataclass
class StandardizedRegion(CFBase):
    description: str = dc.field(default="", compare=False)

@dc.dataclass
class StandardNameAlias(CFBase):
    xml_tag = "alias"
    alias: str = dc.field(default="", metadata={'xml_key':'entry_id'})

@dc.dataclass
class StandardNameAliasAMIP(CFBase):
    alias: str = dc.field(default="", metadata={'xml_key':'amip'})

@dc.dataclass
class StandardNameAliasGRIB(CFBase):
    alias: str = dc.field(default="", metadata={'xml_key':'grib'})

# --------------------------------------------------------------

class RevisionDateList(object):
    def __init__(self, d=None):
        if d is None:
            self._d = dict()
        else:
            self._d = d

    @classmethod
    def from_struct(cls, d):
        return cls({
            k: datetime.date.fromisoformat(v) for k,v in d.items()
        })

    def to_struct(self):
        return {k: v.isoformat() for k, v in self._d.items()}

    def add_modified_date_from_xml(self, xml_root, current_version):
        if current_version == _CURRENT_V:
            mod_dt = datetime.date.today()
        else:
            mod_dt = None
        fld = xml_root.find('last_modified')
        if fld is not None and mod_dt is None:
            # current date tag format used by CF conventions
            try:
                dt = datetime.datetime.strptime(fld.text, '%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                dt = datetime.datetime.strptime(fld.text, '%Y-%m-%dT%H:%MZ')
            mod_dt = dt.date()
        fld = xml_root.find('date')
        if fld is not None and mod_dt is None:
            # older date tag format used by CF conventions
            dt = datetime.datetime.strptime(fld.text, '%d %B %Y')
            mod_dt = dt.date()
        if mod_dt is None:
            warnings.warn("Couldn't find modification date in file {}.".format(
                current_version))
            # If date not given, assign dummy value so that lookup will work
            mod_dt = datetime.date(1900,1,1) 

        self._d[str(current_version)] = mod_dt

    def date_from_version(self, version):
        return self._d.get(str(version), None)

    def version_from_date(self, dt):
        keys = list(self._d.keys())
        dts = list(self._d.values())
        if dts != sorted(dts):
            raise ValueError("Revision dates not in sorted order; lookup will fail")
        idx = bisect.bisect_right(dts, dt)
        if idx == 0:
            return keys[0]
        else:
            return keys[idx - 1]
