# Author: Karl Gemayel
# Created: 6/22/20, 4:43 PM

import logging
import argparse
import pandas as pd
from typing import *
import matplotlib.pyplot as plt

# noinspection All
import pathmagic

# noinspection PyUnresolvedReferences
import mg_log  # runs init in mg_log and configures logger

# Custom imports
from mg_container.genome_list import GenomeInfoList, GenomeInfo
from mg_container.mgm_model import MGMModel
from mg_general import Environment, add_env_args_to_parser
from mg_viz.colormap import ColorMap as CM

# ------------------------------ #
#           Parse CMD            #
# ------------------------------ #
from mg_general.general import os_join, fix_names, next_name
from mg_io.general import mkdir_p
from mg_models.shelf import run_gms2_with_component_toggles_and_get_accuracy, component_in_model_file, \
    run_mgm_and_get_accuracy
from mg_viz import sns
from mg_viz.general import FigureOptions

parser = argparse.ArgumentParser("Test MGM2 model on verified set.")

parser.add_argument('--pf-gil', required=True, help="Genome information list")
parser.add_argument('--pf-mgm', required=True)
parser.add_argument('--component', choices=["Start Codons", "Start Context", "RBS", "Promoter"])

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


def test_component_for_gi(env, gi, pf_mgm, component):
    # type: (Environment, GenomeInfo, str, str) -> pd.DataFrame

    list_entries = list()

    pd_gi = os_join(env["pd-work"], gi.name)
    mkdir_p(pd_gi)

    start_components = {
        "Start Codons", "Start Context", "RBS", "Promoter",
    }
    components_off = start_components.difference({component})

    # test GMS2, MGM, MGM2, and MGM2*
    env_dup = env.duplicate({"pd-work": pd_gi})

    ##### GMS2
    results = run_gms2_with_component_toggles_and_get_accuracy(env_dup, gi, set(), native_coding_off=False)
    list_entries.append({"Tool": "GMS2", **results})

    ##### MGM + native component: MGM with native trained component
    results = run_gms2_with_component_toggles_and_get_accuracy(env_dup, gi, components_off, native_coding_off=True)
    list_entries.append({"Tool": f"MGM: Native {component}", **results})

    ##### MGM + GC component: MGM from new model
    results = run_mgm_and_get_accuracy(env_dup, gi, pf_mgm)
    list_entries.append({"Tool": f"MGM: GC {component}", **results})

    ##### MGM
    results = run_mgm_and_get_accuracy(env_dup, gi, os_join(env["pd-bin-external"], "gms2", "mgm_11.mod"))
    list_entries.append({"Tool": f"MGM", **results})

    return pd.DataFrame(list_entries)


def test_component_on_verified(env, gil, pf_mgm, component):
    # type: (Environment, GenomeInfoList, str, str) -> None

    list_df = list()

    for gi in gil:
        list_df.append(test_component_for_gi(env, gi, pf_mgm, component))

        list_df[-1]["Genome"] = gi.name

    df = pd.concat(list_df, ignore_index=True, sort=False)

    df["Genome"] = df.apply(fix_names, axis=1)
    print(df.to_csv())

    fig, ax = plt.subplots(figsize=(12, 4))
    sns.barplot(df, "Genome", "Error", hue="Tool",
                ax=ax,
                figure_options=FigureOptions(
                    save_fig=next_name(env["pd-work"])
                ),
                )


def main(env, args):
    # type: (Environment, argparse.Namespace) -> None

    gil = GenomeInfoList.init_from_file(args.pf_gil)
    test_component_on_verified(env, gil, args.pf_mgm, args.component)


if __name__ == "__main__":
    main(my_env, parsed_args)
