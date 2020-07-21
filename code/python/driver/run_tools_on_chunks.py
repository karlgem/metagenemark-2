# Author: Karl Gemayel
# Created: 7/20/20, 3:43 PM

import logging
import argparse
import os
import pandas as pd
from subprocess import CalledProcessError
from typing import *
from Bio import SeqIO
from Bio.SeqRecord import SeqRecord

# noinspection All
import pathmagic

# noinspection PyUnresolvedReferences
import mg_log  # runs init in mg_log and configures logger

# Custom imports
from mg_container.genome_list import GenomeInfoList, GenomeInfo
from mg_general import Environment, add_env_args_to_parser
import mg_argparse.parallelization
from mg_general.general import get_value, os_join
from mg_general.genome_splitter import GenomeSplitter
from mg_general.labels import Labels
from mg_io.general import remove_p, mkdir_p
from mg_io.labels import read_labels_from_file, write_labels_to_file
from mg_models.shelf import run_gms2, run_prodigal, run_meta_prodigal, run_mgm2, run_mgm
from mg_options.parallelization import ParallelizationOptions
from mg_parallelization.generic_threading import run_slice_per_thread, run_n_per_thread
from mg_parallelization.pbs import PBS
from mg_pbs_data.mergers import merge_identity
from mg_pbs_data.splitters import split_gil
from mg_viz.shelf import mkstemp_closed


# ------------------------------ #
#           Parse CMD            #
# ------------------------------ #


parser = argparse.ArgumentParser("Run tools on genome chunks.")


parser.add_argument('--pf-gil', required=True)
parser.add_argument('--tools', required=True, nargs="+", choices=["gms2", "mgm", "mgm2",
                                                                  "mprodigal", "prodigal"], type=str.lower)
parser.add_argument('--dn_tools', nargs="+")
parser.add_argument('--pf-summary', required=True, help="Output file that will contain summary of runs")
parser.add_argument('--force-split-in-intergenic', action='store_true')


parser.add_argument('--pf-mgm2-mod', type=os.path.abspath)
parser.add_argument('--pf-mgm-mod', type=os.path.abspath)
parser.add_argument('--chunk-sizes-nt', nargs="+", default=[10000, 50000, 1000000], type=int)
mg_argparse.parallelization.add_parallelization_options(parser)

add_env_args_to_parser(parser)
parsed_args = parser.parse_args()

# ------------------------------ #
#           Main Code            #
# ------------------------------ #

# Load environment variables
my_env = Environment.init_from_argparse(parsed_args)

# Setup logger
logging.basicConfig(level=parsed_args.loglevel)
logger = logging.getLogger("logger")  # type: logging.Logger


def read_sequences_for_gi(env, gi):
    # type: (Environment, GenomeInfo) -> Dict[str, SeqRecord]
    pf_sequence = os_join(env["pd-data"], gi.name, "sequence.fasta")
    return SeqIO.to_dict(SeqIO.parse(pf_sequence, "fasta"))


def read_labels_for_gi(env, gi, fn_labels="ncbi.gff"):
    # type: (Environment, GenomeInfo, str) -> Labels
    pf_labels = os_join(env["pd-data"], gi.name, fn_labels)
    return read_labels_from_file(pf_labels)


def run_tool_on_chunk(env, tool, pf_sequences, pf_prediction, **kwargs):
    # type: (Environment, str, str, str, Dict[str, Any]) -> None
    skip_if_exists = get_value(kwargs, "skip_if_exists", False)
    pf_mgm2_mod = get_value(kwargs, "pf_mgm2_mod", required=tool == "mgm2")
    pf_mgm_mod = get_value(kwargs, "pf_mgm_mod", required=tool == "mgm")

    if skip_if_exists and os.path.isfile(pf_prediction):
        return

    try:
        if tool == "gms2":
            run_gms2(env, pf_sequences, pf_prediction, **kwargs)
        elif tool == "prodigal":
            run_prodigal(env, pf_sequences, pf_prediction, **kwargs)
        elif tool == "mprodigal":
            run_meta_prodigal(env, pf_sequences, pf_prediction, **kwargs)
        elif tool == "mgm2":
            run_mgm2(env, pf_sequences, pf_mgm2_mod, pf_prediction)
        elif tool == "mgm":
            run_mgm(env, pf_sequences, pf_mgm_mod, pf_prediction)
        else:
            raise NotImplementedError()
    except CalledProcessError:
        logger.warning(f"Could not run {tool} on {pf_sequences}")


def run_tools_on_chunk(env, gi, tools, chunk, **kwargs):
    # type: (Environment, GenomeInfo, List[str], int, Dict[str, Any]) -> pd.DataFrame
    dn_tools = get_value(kwargs, "dn_tools", tools)

    # split genome into chunks
    gs = GenomeSplitter(
        read_sequences_for_gi(env, gi), chunk,
        labels=read_labels_for_gi(env, gi),
        allow_splits_in_cds=kwargs.get("allow_splits_in_cds")
    )

    # FIXME: Account for GMS2
    pf_chunks = mkstemp_closed(dir=env["pd-work"], suffix=".fasta")
    gs.write_to_file(pf_chunks)

    list_entries = list()

    for t, dn in zip(tools, dn_tools):
        logger.debug(f"{gi.name};{chunk};{t}")

        pd_run = os_join(env["pd-work"], gi.name, f"{dn}_{chunk}")
        mkdir_p(pd_run)
        pf_prediction = os_join(pd_run, "prediction.gff")
        run_tool_on_chunk(
            env.duplicate({"pd-work": pd_run}), t, pf_chunks, pf_prediction, **kwargs
        )

        # update labels file based on offset
        labels = read_labels_from_file(pf_prediction, shift=0)
        seqname_to_offset = {x[0].id: x[1] for x in gs.split_sequences_}
        for l in labels:
            l.coordinates().left += seqname_to_offset[l.seqname()]
            l.coordinates().right += seqname_to_offset[l.seqname()]
            l.set_seqname(l.seqname().split("_offset")[0])
        write_labels_to_file(labels, pf_prediction, shift_coordinates_by=0)

        list_entries.append({
            "Genome": gi.name,
            "Tool": t,
            "Chunk Size": chunk,
            "Predictions": pf_prediction
        })

    remove_p(pf_chunks)

    return pd.DataFrame(list_entries)


def run_tools_on_gi(env, gi, tools, chunks, **kwargs):
    # type: (Environment, GenomeInfo, List[str], List[int], Dict[str, Any]) -> pd.DataFrame

    num_processors = get_value(kwargs, "num_processors", 1, valid_type=int)

    if num_processors > 1:
        list_df = run_n_per_thread(chunks, run_tools_on_chunk, "chunk",
                         {
                             "env": env, "gi": gi, "tools": tools, **kwargs
                         })


    else:

        list_df = list()
        for chunk in chunks:
            logger.debug(f"{gi.name};{chunk}")
            curr = run_tools_on_chunk(env, gi, tools, chunk, **kwargs)
            list_df.append(curr)

    return pd.concat(list_df, sort=False, ignore_index=True)


def run_tools_on_gil(env, gil, tools, chunks, **kwargs):
    # type: (Environment, GenomeInfoList, List[str], List[int], Dict[str, Any]) -> None
    for gi in gil:
        run_tools_on_gi(env, gi, tools, chunks, **kwargs)

def main(env, args):
    # type: (Environment, argparse.Namespace) -> None

    gil = GenomeInfoList.init_from_file(args.pf_gil)
    prl_options = ParallelizationOptions.init_from_dict(env, args.pf_parallelization_options, vars(args))

    tools = args.tools
    chunks = args.chunk_sizes_nt
    dn_tools = args.dn_tools if args.dn_tools is not None else tools

    # check that both have the same length
    if len(tools) != len(dn_tools):
        raise ValueError(f"The 'tools' and 'dn-tools' arguments"
                         f" must have equal lengths: {len(tools)} != {len(dn_tools)}")

    if prl_options["use-pbs"]:
        pbs = PBS(env, prl_options, splitter=split_gil, merger=merge_identity)
        list_df = pbs.run(
            gil, run_tools_on_gil,
            {
                "env": env, "tools": tools, "chunks": chunks, "dn_tools": dn_tools,
                "pf_mgm2_mod": args.pf_mgm2_mod,
                "pf_mgm_mod": args.pf_mgm_mod,
                "num_processors": prl_options.safe_get("pbs-ppn"),
                "allow_splits_in_cds": not args.force_split_in_intergenic
            }
        )
        df = pd.concat(list_df, ignore_index=True, sort=False)

    else:
        list_df = run_n_per_thread(
            list(gil), run_tools_on_gi, "gi", {
                "env": env, "chunks": chunks, "tools": tools, "dn_tools": dn_tools,
                "pf_mgm2_mod": args.pf_mgm2_mod,
                "pf_mgm_mod": args.pf_mgm_mod,
                "num_processors": 1,
                "allow_splits_in_cds": not args.force_split_in_intergenic
            }, simultaneous_runs=7
        )

        df = pd.concat(list_df, sort=False, ignore_index=True)

    df.to_csv(args.pf_summary, index=False)


if __name__ == "__main__":
    main(my_env, parsed_args)
