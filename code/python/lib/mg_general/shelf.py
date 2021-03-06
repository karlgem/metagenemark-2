# Author: karl
# Created: 2020-06-21, 8:56 a.m.

import logging
from itertools import chain, combinations
from typing import *

from Bio.SeqRecord import SeqRecord

from mg_general.labels import Label

log = logging.getLogger(__name__)


def test_log_level():
    log.debug(f"Test")
    log.info(f"Test")
    log.warning(f"Test")
    log.critical(f"Test")


def list_find_first(a_list, a_filter):
    # type: (List[Any], Callable) -> Any
    for x in a_list:
        if a_filter(x):
            return x
    return None


def compute_gc(sequences, label=None):
    # type: (Dict[str, SeqRecord], Union[Label, None]) -> float

    gc_percent = 0

    if label is None:
        gc = at = 0
        for seqname, seqrecord in sequences.items():
            for i in range(len(seqrecord)):
                l = seqrecord[i].upper()
                if l == "G" or l == "C":
                    gc += 1
                elif l == "A" or l == "T":
                    at += 1

        total = gc + at
        if total != 0:
            gc_percent = 100.0 * gc / float(total)
    else:
        if label.seqname() in sequences.keys():
            seqrecord = sequences[label.seqname()]
            gc = at = 0
            for i in range(label.left(), label.right()):
                l = seqrecord[i].upper()
                if l == "G" or l == "C":
                    gc += 1
                elif l == "A" or l == "T":
                    at += 1
            total = gc + at
            if total != 0:
                gc_percent = 100.0 * gc / float(total)

    return gc_percent


def powerset(iterable, min_len=0):
    """powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)"""
    s = list(iterable)
    return [x for x in chain.from_iterable(combinations(s, r) for r in range(min_len, len(s) + 1))]