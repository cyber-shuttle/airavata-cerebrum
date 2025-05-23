import collections.abc
import logging
import os
import subprocess
import time
import typing as t

#
import anndata
import duckdb
import numpy as np
import numpy.typing as npt
import matplotlib.pyplot as plt
import pandas as pd
import polars as pl
#
from typing_extensions import override
from pathlib import Path
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from pydantic import Field
from abc_atlas_access.abc_atlas_cache.abc_project_cache import AbcProjectCache
#
from ..base import CerebrumBaseModel, DbQuery, BaseParams, QryDBWriter, QryItr

ProcessResult : t.TypeAlias = subprocess.CompletedProcess[bytes]
NDFloatArray : t.TypeAlias = npt.NDArray[np.floating[t.Any]]
DictDataFrame: t.TypeAlias = dict[str, pd.DataFrame]

PARCEL_META_DATA_KEY = "cell_metadata_with_parcellation_annotation"
MERFISH_CCF_DATASET_KEY = "MERFISH-C57BL6J-638850-CCF"
PARCELLATION_SUBSTRUCTURE = "parcellation_substructure"
PARCELLATION_STRUCTURE = "parcellation_structure"
# Column Names
# Glut subclasses
GLUT_IT_SUBCLASS_SETMAP = {
    "IT-ENT": set(
        [
            "003 L5/6 IT TPE-ENT Glut",
            "008 L2/3 IT ENT Glut",
            "009 L2/3 IT PIR-ENTl Glut",
            "011 L2 IT ENT-po Glut",
        ]
    ),
    "IT-CTX": set(
        [
            "004 L6 IT CTX Glut",
            "005 L5 IT CTX Glut",
            "006 L4/5 IT CTX Glut",
            "007 L2/3 IT CTX Glut",
        ]
    ),
    "IT-Other": set(
        [
            "002 IT EP-CLA Glut",
            "010 IT AON-TT-DP Glut",
            "018 L2 IT PPP-APr Glut",
            "019 L2/3 IT PPP Glut",
            "020 L2/3 IT RSP Glut",
        ]
    ),
}
GLUT_SUBCLASS_SETMAP = {
    "ET": set(["022 L5 ET CTX Glut"]),
    "CT": set(["028 L6b/CT ENT Glut", "030 L6 CT CTX Glut", "031 CT SUB Glut"]),
    "NP": set(["032 L5 NP CTX Glut", "033 NP SUB Glut", "034 NP PPP Glut"]),
    "IT": set.union(*GLUT_IT_SUBCLASS_SETMAP.values()),
}
GLUT = "Glut"
GLUT_TYPES = list(GLUT_SUBCLASS_SETMAP.keys())
GLUT_IT_TYPES = list(GLUT_IT_SUBCLASS_SETMAP.keys())
GLUT_COLUMNS = [GLUT] + GLUT_TYPES + GLUT_IT_TYPES + ["Glut-Other"]
#
# GABA subclasses
GABA_SUBCLASS_SETMAP = {
    "Vip": set(["046 Vip Gaba"]),
    "Pvalb": set(["051 Pvalb chandelier Gaba", "052 Pvalb Gaba"]),
    "Sst": set(["053 Sst Gaba", "265 PB Sst Gly-Gaba"]),
    "Lamp5": set(["049 Lamp5 Gaba", "050 Lamp5 Lhx6 Gaba"]),
    "Sst-Chodl": set(["056 Sst Chodl Gaba"])
}
GABA = "GABA"
GABA_TYPES = list(GABA_SUBCLASS_SETMAP.keys())
GABA_COLUMNS = [GABA] + list(GABA_SUBCLASS_SETMAP.keys()) + ["GABA-Other"]
#
FRACTION_COLUMN_FMT = "{} fraction"
INHIBITORY_FRACTION_COLUMN = "inhibitory fraction"
FRACTION_WI_REGION_COLUMN = "fraction wi. region"


def _log():
    return logging.getLogger(__name__)


def abc_cache_download_meta(download_base: str | Path,
                            abc_data_key: str,
                            meta_key: str | None) -> str | Path | None:
    """
    Download meta data frame obtained with
        - download_base as the cached directory,
        - abc_data_key as the dataset name and
        - meta key to indicate the meta file

    Downloads the meta data if not already downloaded

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    abc_data_key : str
        data key should be one of cache's list_directories
    meta_key : str
        data key should be one of meta file names of the given directory

    Returns
    -------
    pandas.DataFrame
       Cell meta data for each of the cell, with each row being a cell.

    """
    pcache = AbcProjectCache.from_s3_cache(download_base)
    pcache.load_manifest()
    if abc_data_key not in pcache.list_directories:
        _log().error(
            "Meta data directory not one of valid dirs %s ", pcache.list_directories
        )
        return None
    try:
        metadata_path = pcache.get_directory_metadata(abc_data_key)
        if meta_key:
            metadata_path = pcache.get_metadata_path(abc_data_key, meta_key)
        return metadata_path
    except Exception as ex:
        _log().error("Exception occurred in download %s ", ex)
    return None


def abc_cache_download_exp_mat(download_base: str | Path,
                               abc_data_key: str,
                               gex_key: str | None) -> str | Path | None:
    """
    Download data frame obtained with
        - download_base as the cached directory,
        - abc_data_key as the dataset name,
        - gex_key as the file key within the dataset

    Downloads the meta data if not already downloaded

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    abc_data_key : str
        data key should be one of cache's list_directories
    gex_key : str
        data key should be one of gene exp file names of the given directory

    Returns
    -------
    pandas.DataFrame
       Cell meta data for each of the cell, with each row being a cell.

    """
    pcache = AbcProjectCache.from_s3_cache(download_base)
    pcache.load_manifest()
    if abc_data_key not in pcache.list_directories:
        _log().error(
            "Meta data directory not one of valid dirs %s ", pcache.list_directories
        )
        return None
    try:
        data_path = pcache.pcache.get_directory_data(abc_data_key)
        if gex_key is not None:
            data_path = pcache.get_data_path(abc_data_key, gex_key)
        return data_path
    except Exception as ex:
        _log().error("Exception occurred in download %s ", ex)
    return None


def abc_cache_download_all_meta_data(download_base: str | Path) -> None:
    """
    Download all the metadata files using ABC Cache object.

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded

    Returns
    -------
    list
        List of return values of the executions download commands.
    """
    pcache = AbcProjectCache.from_s3_cache(download_base)
    pcache.load_manifest()
    for rdir in pcache.list_directories:
        abc_cache_download_meta(download_base, rdir, None)


def download_merfish_manifest(
    download_base : str | Path = "./cache/abc_mouse"
) -> dict[str, t.Any]:
    """
    Downloads the Manifiest JSON data using the Cache

    Parameters
    ----------
    download_base : str (default: ./cache/abc_mouse)
        Base directory on to which the file will be downloaded in the relative
        path.

    Returns
    -------
    manifest: dict
        manifest json as a dict
    """
    pcache = AbcProjectCache.from_s3_cache(download_base)
    pcache.load_manifest()
    manifest = pcache.cache._manifest.data
    return manifest


def merfish_files_meta(
        download_base : str | Path = "./cache/abc_mouse",
        abc_data_key : str = "MERFISH-C57BL6J-638850"
) -> tuple[dict[str, t.Any], dict[str, t.Any]]:
    """
    Downloads the Manifiest JSON data from ABC AWS Store and retrieve
    MERFISH-C57BL6J-638850 meta data JSON object.

    Parameters
    ----------
    download_base : str (default: ./cache/abc_mouse)
        Base directory on to which the file will be downloaded in the relative
        path.

    Returns
    -------
    tuple
        manifest, merf_data : manifest is dict representation of the json,
        merf_data is the value at
        manifest["file_listing"]["MERFISH-C57BL6J-638850"]["metadata"]

    """
    manifest = download_merfish_manifest(download_base)
    merf_meta = manifest["file_listing"][abc_data_key]["metadata"]
    return manifest, merf_meta


def aws_s3_copy(
    remote_path: str | Path,
    local_path: str | Path
) -> ProcessResult:
    """
    Run aws s3 cp command from remote_path to local_path

    Parameters
    ----------
    remote_path : str | Path
        Remove AWS path
    local_path: str | Path
        Local path

    Returns
    -------
    subprocess.CompletedProcess
        Return value of the aws download command.

    """
    # Download command
    command = "aws s3 cp --no-sign-request %s %s" % (remote_path, local_path)
    print(command)
    # Run download command
    start = time.process_time()
    # Uncomment to download file
    result = subprocess.run(command.split(" "), stdout=subprocess.PIPE)
    print("time taken: ", time.process_time() - start)
    return result


def aws_s3_sync(
    remote_path: str | Path,
    local_path: str | Path
) -> ProcessResult:
    """
    Run aws s3 sync command from remote_path to local_path

    Parameters
    ----------
    remote_path : str | Path
        Remove AWS path
    local_path: str | Path
        Local path

    Returns
    -------
    subprocess.CompletedProcess
        Return value of the aws download command.

    """
    command_pattern = "aws s3 sync --no-sign-request %s %s"
    command = command_pattern % (remote_path, local_path)
    print(command)
    #
    start = time.process_time()
    # Uncomment to download directories
    result = subprocess.run(command.split(), stdout=subprocess.PIPE)
    print("time taken: ", time.process_time() - start)
    return result


def aws_download_file(
    download_base: str | Path,
    manifest: dict[str, dict[str, t.Any]],
    file_dict: dict[str, t.Any],
) -> ProcessResult:
    """
    Given a file entry in manifest, download the file using AWS CLI 'aws'
    to the relative path constructed from the download_base.
    Assumes that the aws command is available is installed in the current
    environment.

    A simple file entry in manifest is as follows:
    {
     'version': '20230630',
     'relative_path': 'expression_matrices/WMB-10Xv3/20230630',
     'url': 'https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/expression_matrices/WMB-10Xv3/20230630/',
     'view_link':
     'https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/index.html#expression_matrices/WMB-10Xv3/20230630/',
     'total_size': 189424020276
    }

    Parameters
    ----------
    manifest : dict
        manifest json as a dict
    file_dict : dict
        file entry within the manifest json as a dict. An example:
        {
         'version': '20230630',
         'relative_path': 'expression_matrices/WMB-10Xv3/20230630',
         'url': 'https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/expression_matrices/WMB-10Xv3/20230630/',
         'view_link':
         'https://allen-brain-cell-atlas.s3.us-west-2.amazonaws.com/index.html#expression_matrices/WMB-10Xv3/20230630/',
         'total_size': 189424020276
        }
    download_base : str
        Base directory on to which the file will be downloaded in the relative
        path.

    Returns
    -------
    subprocess.CompletedProcess
        Return value of the aws download command.

    """
    print(file_dict["relative_path"], file_dict["size"])
    local_path = os.path.join(download_base, file_dict["relative_path"])
    local_path = Path(local_path)
    remote_path = manifest["resource_uri"] + file_dict["relative_path"]
    return aws_s3_copy(remote_path, local_path)


def download_size(
    manifest: dict[str, t.Any]
) -> dict[str, float]:
    """
    Construct a dictionary containing the file sizes in GB given in the
    manifest

    Parameters
    ----------
    manifest : dict
        manifest json as a dict.

    Returns
    -------
    dict
        A dictionary containing the file sizes in GB of each of the files.
    """
    to_gb = float(float(1024) ** 3)
    #
    file_size_dict = {}
    for r in manifest["directory_listing"]:
        r_dict = manifest["directory_listing"][r]
        for d in r_dict["directories"]:
            d_dict = r_dict["directories"][d]
            file_gb = d_dict["total_size"] / to_gb
            print(d_dict["relative_path"], ":", "%0.2f GB" % (file_gb))
            file_size_dict[d_dict["relative_path"]] = file_gb
    return file_size_dict


def aws_download_meta_data(
    manifest: dict[str, t.Any],
    download_base: str | Path
)-> list[ProcessResult]:
    """
    Download all the metadata files using AWS CLI listed in the manifest to
    download_base.
    Assumes that the AWS command line excutable is available and installed.

    Parameters
    ----------
    manifest : dict
        manifest json as a dict.
    download_base: str
        Directory to which meta data is to be downloaded

    Returns
    -------
    list
        List of return values of the executions download commands.
    """
    download_results = []
    for r in manifest["directory_listing"]:
        r_dict = manifest["directory_listing"][r]
        for d in r_dict["directories"]:
            #
            if d != "metadata":
                continue
            d_dict = r_dict["directories"][d]
            local_path = os.path.join(download_base, d_dict["relative_path"])
            local_path = Path(local_path)
            remote_path = manifest["resource_uri"] + d_dict["relative_path"]
            #
            result = aws_s3_sync(remote_path, local_path)
            download_results.append(result)
    return download_results


def abc_cache_download_abc_exp_matrices(
    download_base: str | Path,
    exp_mat_dict: dict[str, list[str]] | None = None,
) -> None:
    """
    Download the following genes expression matrices listed in the dict
    gene_exp_dict : {"data"}

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    exp_mat_dict: dict
        dict mapping string to a lit of matrix entry keys

    Returns
    -------
    list
        List of return values of the executions download commands.
    """
    if exp_mat_dict is None:
        exp_mat_dict = {
            "MERFISH-C57BL6J-638850" : ["C57BL6J-638850/log2"],
            "WMB-10Xv2" : ["WMB-10Xv2-TH/log2"],
            "Zhuang-ABCA-1" : ["Zhuang-ABCA-1/log2"],
            "Zhuang-ABCA-2" : ["Zhuang-ABCA-2/log2"],
            "Zhuang-ABCA-3" : ["Zhuang-ABCA-3/log2"],
            "Zhuang-ABCA-4" : ["Zhuang-ABCA-4/log2"]
        }
    for data_key, exp_file_lst in exp_mat_dict.items():
        for exp_file_key in exp_file_lst:
            abc_cache_download_exp_mat(download_base, data_key, exp_file_key)


def aws_download_abc_exp_matrices(
    download_base: Path,
    manifest : dict[str, t.Any],
    dataset_exp_keys: dict[str, str] | None = None,
) -> list[ProcessResult]:
    """
    Download the genes expression matrices listed in the dataset_exp_keys
    from the location described by the manifest to download_base location.

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    manifest : dict
        manifest json as a dict.
    download_exp_keys: dict[str, str]
        Dictonary of the database key mapping to the entry keys

    Returns
    -------
    list
        List of return values of the executions download commands.
    """
    if dataset_exp_keys is None:
        dataset_exp_keys = {
            "WMB-10Xv2": "WMB-10Xv2-TH",
            "MERFISH-C57BL6J-638850": "C57BL6J-638850",
            "Zhuang-ABCA-1": "Zhuang-ABCA-1",
            "Zhuang-ABCA-2": "Zhuang-ABCA-2",
            "Zhuang-ABCA-3": "Zhuang-ABCA-3",
            "Zhuang-ABCA-4": "Zhuang-ABCA-4"
        }
    download_results = []
    start = time.process_time()
    # Downloading data Expresssion matrices
    for d, lk in dataset_exp_keys.items():
        exp_matrices = manifest["file_listing"][d]["expression_matrices"]
        file_dict = exp_matrices[lk]["log2"]["files"]["h5ad"]
        print("size:", file_dict["size"])
        result = aws_download_file(download_base, manifest, file_dict)
        download_results.append(result)
    print("time taken: ", time.process_time() - start)
    return download_results


def aws_download_image_volumes(
    download_base: str | Path,
    manifest: dict[str, t.Any],
) -> list[ProcessResult]:
    """
    Download all the image volumes listed in the manifest to download_base

    Parameters
    ----------
    manifest : dict
        manifest json as a dict.
    download_base: str
        Directory to which meta data is to be downloaded

    Returns
    -------
    list
        List of return values of the executions download commands.
    """
    download_results = []
    for r in manifest["directory_listing"]:
        r_dict = manifest["directory_listing"][r]
        for d in r_dict["directories"]:
            if d != "image_volumes":
                continue
            d_dict = r_dict["directories"][d]
            local_path = os.path.join(download_base, d_dict["relative_path"])
            local_path = Path(local_path)
            remote_path = manifest["resource_uri"] + d_dict["relative_path"]
            result = aws_s3_sync(remote_path, local_path)
            download_results.append(result)
    return download_results


def download_abc_data(
    download_base: str | Path,
    image_download: bool = False
) -> None:
    """
    Downloads meta data, gene expression matrices and the image volumes to the
    download_base directory.

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    image_download : bool (default: False)
        Flag to indicate if images are to be downloaded

    Returns
    -------
    None
    """
    abc_cache_download_all_meta_data(download_base)
    abc_cache_download_abc_exp_matrices(download_base)
    if image_download:
        manifest = download_merfish_manifest(download_base)
        aws_download_image_volumes(download_base, manifest)


def taxonomy_meta(
    download_base: str | Path,
    abc_data_key: str,
    meta_key: str
) -> pd.DataFrame | None:
    """
    Return the taxonomy meta data, as located in data_key, from download_base.
    The relative paths to the meta data files in download_base are obtaned from
    the manifest JSON object.

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    abc_data_key : str
        Dataset identfier
    meta_key : str
        Meta data identfier

    Returns
    -------
    pandas.DataFrame
       Taxonomy data for each of the cell, with each row being a cell.
    """

    metadata_path = abc_cache_download_meta(download_base, abc_data_key, meta_key)
    if metadata_path is None:
        return None
    taxnm_meta_df = pd.read_csv(metadata_path, keep_default_na=False)
    if "cluster_alias" in taxnm_meta_df.columns:
        taxnm_meta_df.set_index("cluster_alias", inplace=True)
    return taxnm_meta_df


def taxonomy_cluster(
    download_base: str | Path
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """
    Return the taxonomy meta data, specifically cluster name annotation and the
    colors assigned for the clusters, from download_base.
    The relative paths to the meta data files in download_base are obtaned from
    the manifest JSON object.

    Parameters
    ----------
    manifest : dict
        manifest json as a dict.
    download_base: str
        Directory to which meta data is to be downloaded

    Returns
    -------
    (pandas.DataFrame, pandas.DataFrame)
       Cluster name and Cluster colors as two data frames for each of the cell,
       with each row being a cell.
    """
    #  Cluster Details from Taxonomy Data
    cluster_details = taxonomy_meta(
        download_base,
        "WMB-taxonomy",
        "cluster_to_cluster_annotation_membership_pivoted",
    )
    #
    # Membership Color
    cluster_colors = taxonomy_meta(
        download_base, "WMB-taxonomy", "cluster_to_cluster_annotation_membership_color"
    )
    return cluster_details, cluster_colors


def cell_metadata(
    download_base : str | Path,
    abc_data_key : str = "MERFISH-C57BL6J-638850"
) -> pd.DataFrame | None:
    """
    Cell meta data frame obtained with download_base as the cached directory.
    Downloads the meta data if not already downloaded

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    abc_data_key : str ("MERFISH-C57BL6J-638850")
        Data directory in ABC

    Returns
    -------
    pandas.DataFrame
       Cell meta data for each of the cell, with each row being a cell.

    """
    metadata_path = abc_cache_download_meta(
        download_base, abc_data_key, "cell_metadata"
    )
    if metadata_path is None:
        return None
    cell_df = pd.read_csv(metadata_path, dtype={"cell_label": str})
    cell_df.set_index("cell_label", inplace=True)
    return cell_df


def gene_metadata(
    download_base : str | Path,
    abc_data_key : str = "MERFISH-C57BL6J-638850"
) -> pd.DataFrame | None:
    """
    Gene meta data frame obtained with download_base as the cached directory.
    Downloads the meta data if not already downloaded

    Parameters
    ----------
    download_base: str
        Directory to which meta data is to be downloaded
    abc_data_key : str ("MERFISH-C57BL6J-638850")
        Data directory in ABC

    Returns
    -------
    pandas.DataFrame
       Gene meta data for each of the cell, with each row being a gene.
    """
    # Gene Data Information
    metadata_path = abc_cache_download_meta(download_base, abc_data_key, "gene")
    if metadata_path is None:
        return None
    gene_df = pd.read_csv(metadata_path)
    gene_df.set_index("gene_identifier", inplace=True)
    return gene_df


def gene_expression_matrix(
    download_base : str | Path,
    source : str = "MERFISH-C57BL6J-638850",
    file_id: str = "C57BL6J-638850/log2",
) -> anndata.AnnData | None:
    """
    Gene expression matrix of data id (default 'C57BL6J-638850') from the
    download_base directory. source(default 'MERFISH-C57BL6J-638850') entry
    is used to obtain the expression matrix JSON manifest.
    """
    # gene expresssion data
    # expmat_manifest = manifest["file_listing"][source]["expression_matrices"]
    # rpath = expmat_manifest[data_id][transform]["files"]["h5ad"]["relative_path"]
    # file = os.path.join(download_base, rpath)
    data_file = abc_cache_download_exp_mat(download_base, source, file_id)
    if data_file is None:
        return None
    adata = anndata.read_h5ad(data_file, backed="r")
    return adata

def plot_section(
    xx: NDFloatArray,
    yy: NDFloatArray,
    cc: str | None =None,
    val: str | None=None,
    fig_width: int=8,
    fig_height: int=8,
    cmap: str | None =None
)  -> tuple[Figure, Axes]:
    """
    Plot a Section of the MERFISH co-ordinates
    """
    sub_plots : tuple[Figure, Axes] = plt.subplots()
    fig, ax = sub_plots
    fig.set_size_inches(fig_width, fig_height)
    if cmap is not None:
        plt.scatter(xx, yy, s=0.5, c=val, marker=".", cmap=cmap)
    elif cc is not None:
        plt.scatter(xx, yy, s=0.5, color=cc, marker=".")
    ax.set_ylim(11, 0)
    ax.set_xlim(0, 11)
    ax.axis("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    return fig, ax


def create_expression_dataframe(
    adata: pd.DataFrame,
    gene_meta: pd.DataFrame,
    section_meta : pd.DataFrame
):
    """
    Gene expression data frame with the genes and meta data variables as its
    columns
    """
    gdata = adata[:, gene_meta.index].to_df()
    gdata.columns = gene_meta.gene_symbol
    joined = section_meta.join(gdata)
    return joined


def aggregate_by_metadata(
    df: pd.DataFrame,
    gnames: list[str],
    group_value: str,
    sort: bool=False
)-> pd.DataFrame:
    """
    Aggregate gene expression by 'group_value' and report the average gene
    expression values of the list of genes given by 'gnames'
    """
    grouped : pd.DataFrame = df.groupby(
        group_value
    )[gnames].mean() # pyright: ignore[reportAssignmentType]
    if sort:
        grouped = grouped.sort_values(by=gnames[0], ascending=False)
    return grouped


def plot_heatmap(
    df: pd.DataFrame,
    ylabel: str="Expression",
    lmin: int=0,
    lmax: int=5,
    fig_width: int=8,
    fig_height: int=4,
    cmap: str="magma",
):
    """
    Plot Heat Map based on the input data frame
    """
    arr = df.to_numpy()
    sub_plots : tuple[Figure, Axes] = plt.subplots()
    fig, ax = sub_plots
    fig.set_size_inches(
        fig_width,
        fig_height
    )
    im = ax.imshow(
        arr,
        cmap=cmap,
        aspect="auto", 
        vmin=lmin,
        vmax=lmax)
    xlabs = df.columns.values
    ylabs = df.index.values
    ax.set_xticks(range(len(xlabs)))
    ax.set_xticklabels(xlabs)
    ax.set_yticks(range(len(ylabs)))
    ax.set_yticklabels(ylabs)
    plt.setp(ax.get_xticklabels(), rotation=90)
    cbar = ax.figure.colorbar(im, ax=ax)
    cbar.set_label(ylabel)
    return im


def cell_ccf_meta(ccf_meta_file: str | Path) -> pd.DataFrame:
    """
    Data frame containing the Cell Allen CCF Meta
    """
    cell_ccf = pd.read_csv(ccf_meta_file)
    return cell_ccf


def valid_genes_symbols(gene_meta: pd.DataFrame) -> list[str]:
    """
    Genes that doesn't contain 'Blank'
    """
    return gene_meta[~gene_meta.gene_symbol.str.contains("Blank")].gene_symbol.values


def filter_invalid_genes(
    gene_meta: pd.DataFrame,
    valid_genes: list[str] | set[str]):
    """
    Select the valid genes
    """
    # Remove "blank" genes
    pred = [x in valid_genes for x in gene_meta.gene_symbol]
    gf = gene_meta[pred]
    return gf


def predicate_flags_df(area_cell_df: pd.DataFrame,
                       flag_key_map: dict[str, str],
                       select_col: str,
                       pred_fn: t.Callable[[pd.Series, str], pd.Series],
                       exclude_column: str | None = None) -> pd.DataFrame:
    """
    Cell meta data frame with flags added to indicate
    excitatory ('E'), inhibitory ('I'), Other ('O')
    based on whether the class of the cell property "class"
    ends with "Glut" (E) or "GABA" (I)
    """
    pred_dct = {
        flag_column : pred_fn(
            area_cell_df[select_col], # pyright: ignore[reportArgumentType]
            flag_key
        )
        for flag_column, flag_key in flag_key_map.items()
    }
    pred_df = pd.DataFrame(pred_dct)
    if exclude_column:
        pred_df.loc[:, exclude_column] = ~pred_df.any(axis=1)
    return pred_df


def concat_predicate_flags_df(
    area_cell_df: pd.DataFrame,
    flag_key_map: dict[str, str],
    select_col: str,
    pred_fn: t.Callable[[pd.Series, str], pd.Series],
    exclude_column: str | None = None
) -> pd.DataFrame:
    pred_df = predicate_flags_df(area_cell_df, flag_key_map,
                                 select_col, pred_fn, exclude_column)
    return pd.concat([area_cell_df, pred_df], axis=1)


def cell_meta_ei_flags(area_cell_df: pd.DataFrame):
    """
    Cell meta data frame with flags added to indicate
    excitatory ('E'), inhibitory ('I'), Other ('O')
    based on whether the class of the cell property "class"
    ends with "Glut" (E) or "GABA" (I)
    """
    def endswith_pred_fn(df_col: pd.Series, skey: str) -> pd.Series:
        return df_col.str.endswith(skey)
    flag_key_map = {"E": "Glut", "I": "GABA"}
    return concat_predicate_flags_df(area_cell_df, flag_key_map,
                                     "class", endswith_pred_fn, "O")


def cell_meta_subclass_flags(
    area_cell_df: pd.DataFrame,
    subclass_mapset: dict[str, set[str]]
) -> dict[str, pd.Series]:
    pred_subclass = {}
    for kx, subx in subclass_mapset.items():
        pred_subclass[kx] = (
            area_cell_df["subclass"].isin(subx) # pyright: ignore[reportArgumentType]
        )
    return pred_subclass


def cell_meta_gaba_flags(area_cell_df: pd.DataFrame):
    if len(area_cell_df) == 0:
        return area_cell_df
    pred_gaba = area_cell_df["subclass"].str.endswith("Gaba")
    # GABA Sub types
    pred_gaba_subclass_map = cell_meta_subclass_flags(
        area_cell_df, GABA_SUBCLASS_SETMAP
    )
    area_cell_df.loc[:, "GABA"] = pred_gaba
    for kv, pred_series in pred_gaba_subclass_map.items():
        area_cell_df.loc[:, kv] = pred_series
    gaba_classifieds = ["Vip", "Pvalb", "Sst", "Sst-Chodl", "Lamp5"]
    pred_gaba_classified = area_cell_df.loc[:, gaba_classifieds].any(axis="columns")
    area_cell_df.loc[:, "GABA-Other"] = pred_gaba & (~pred_gaba_classified)
    return area_cell_df


def cell_meta_glut_flags(area_cell_df: pd.DataFrame):
    if len(area_cell_df) == 0:
        return area_cell_df
    # Glut Sub-types
    pred_glut = area_cell_df["subclass"].str.endswith("Glut")
    pred_glut_subclass_map = cell_meta_subclass_flags(
        area_cell_df, GLUT_SUBCLASS_SETMAP | GLUT_IT_SUBCLASS_SETMAP
    )
    area_cell_df.loc[:, "Glut"] = pred_glut
    for kv, pred_series in pred_glut_subclass_map.items():
        area_cell_df.loc[:, kv] = pred_series
    glut_classifieds = ["ET", "CT", "IT", "NP"]
    pred_glut_classified = area_cell_df.loc[:, glut_classifieds].any(axis="columns")
    area_cell_df.loc[:, "Glut-Other"] = pred_glut & (~pred_glut_classified)
    return area_cell_df


def cell_meta_type_flags(area_cell_df: pd.DataFrame):
    return cell_meta_glut_flags(
        cell_meta_gaba_flags(
            cell_meta_ei_flags(
                area_cell_df
            )
        )
    )


def cell_meta_type_ratios(
    area_sumdf : pd.DataFrame | pd.Series,
    ax: str,
    nregion: int
) -> pd.DataFrame:
    ratio_df = pd.DataFrame(index=area_sumdf.index)
    #
    ratio_df["Region"] = ax
    ratio_df["Layer"] = [x.replace(ax, "") for x in ratio_df.index]
    ratio_df["nregion"] = nregion
    ratio_df[INHIBITORY_FRACTION_COLUMN] = area_sumdf["I"] / area_sumdf["EI"]
    ratio_df[FRACTION_WI_REGION_COLUMN] = area_sumdf["T"] / nregion
    #
    for colx in GABA_TYPES:
        fraction_col = FRACTION_COLUMN_FMT.format(colx)
        ratio_df[fraction_col] = area_sumdf[colx] / area_sumdf[GABA]
    #
    for colx in GLUT_IT_TYPES:
        fraction_col = FRACTION_COLUMN_FMT.format(colx)
        ratio_df[fraction_col] = area_sumdf[colx] / area_sumdf[GLUT]
    #
    for colx in GLUT_TYPES:
        fraction_col = FRACTION_COLUMN_FMT.format(colx)
        ratio_df[fraction_col] = area_sumdf[colx] / area_sumdf[GLUT]
    return ratio_df

def region_ccf_cell_types(
    cell_ccf: pd.DataFrame,
    region_list: list[str]
) -> tuple[DictDataFrame, DictDataFrame, DictDataFrame]:
    #
    region_ctx_ccf = {}
    region_frac_ccf = {}
    region_cell_ccf = {}
    # Columns
    ei_cols = [PARCELLATION_SUBSTRUCTURE, "E", "I", "O"]
    sel_cols = ei_cols + GABA_COLUMNS + GLUT_COLUMNS
    #
    for region in region_list:
        # Select the CCF meta data specific to the above region
        region_df = cell_ccf.loc[cell_ccf[PARCELLATION_STRUCTURE] == region]
        # Ignore the regions for which no cells are available
        if len(region_df) == 0:
            continue
        # 1. Flags corresponding to meta data
        region_df = region_df.copy()
        region_df = cell_meta_type_flags(region_df)
        # 2. Group by sub structure and find summary counts for each layer
        region_ei_df = region_df[sel_cols].copy()
        region_ei_ctx = region_ei_df.groupby(PARCELLATION_SUBSTRUCTURE).sum()
        region_ei_ctx["T"] = (
            region_ei_ctx["E"] + region_ei_ctx["I"] + region_ei_ctx["O"]
        )  # type:ignore
        region_ei_ctx["EI"] = region_ei_ctx["E"] + region_ei_ctx["I"]  # type: ignore
        n_region_layers = len(region_df)
        region_name = region
        # 3. Compute the ratios
        region_ei_ratio = cell_meta_type_ratios(
            region_ei_ctx,
            region_name,
            n_region_layers
        )
        # Save to the data frame to the dict
        region_cell_ccf[region] = region_df
        region_ctx_ccf[region] = region_ei_ctx
        region_frac_ccf[region] = region_ei_ratio
    return region_cell_ccf, region_ctx_ccf, region_frac_ccf


def region_cell_type_ratios(
    region_name: str,
    download_base: str,
    merfish_ccf_data_key: str=MERFISH_CCF_DATASET_KEY,
    parcel_meta_data_key: str=PARCEL_META_DATA_KEY
):
    # Cell Meta and CCF Meta data
    ccf_meta_file = abc_cache_download_meta(download_base, merfish_ccf_data_key,
                                            parcel_meta_data_key)
    if ccf_meta_file:
        cell_ccf = cell_ccf_meta(ccf_meta_file)
        _, _, region_frac_ccf = region_ccf_cell_types(cell_ccf, [region_name])
        return region_frac_ccf[region_name]


class InitParams(CerebrumBaseModel):
    download_base : t.Annotated[str, Field(title="Download Base")]

class ExecParams(CerebrumBaseModel):
    region  : t.Annotated[list[str] , Field(title="List of Regions")]

CCFParamsBase : t.TypeAlias = BaseParams[InitParams,  ExecParams] 

class ABCDbMERFISH_CCFQuery(DbQuery[InitParams, ExecParams]):
    class QryParams(CCFParamsBase):
        init_params: t.Annotated[InitParams, Field(title='Init Params')]
        exec_params: t.Annotated[ExecParams, Field(title='Exec Params')]

    def __init__(self, init_params: InitParams, **params: t.Any):
        """
        Initialize MERFISH Query
        Parameters
        ----------
        download_base : str (Mandatory)
           File location to store the manifest and the cells.json files

        """
        self.name : str = __name__ + ".ABCDbMERFISHQuery"
        self.download_base : str = init_params.download_base # params["download_base"]
        self.pcache : AbcProjectCache = AbcProjectCache.from_s3_cache(
            self.download_base
        )
        self.pcache.load_latest_manifest()
        self.pcache.get_directory_metadata(MERFISH_CCF_DATASET_KEY)
        self.ccf_meta_file : Path = self.pcache.get_metadata_path(
            MERFISH_CCF_DATASET_KEY, PARCEL_META_DATA_KEY
        )

    @override
    def run(
        self,
        exec_params: ExecParams,
        first_iter: QryItr | None,
        *rest_iter: QryItr | None,
        **params: t.Any,
    ) -> QryItr | None:
        """
        Get the cell types ratios corresponding to a region

        Parameters
        ----------
        run_params: dict with the following keys:
            region : List[str]
             lis of regions of interest
        Returns
        -------
        dict of elements for each sub-region:
        {
            subr_1 : {}
        }
        """
        #
        # default_args = {}
        # rarg = {**default_args, **params} if params else default_args
        _log().info("ABCDbMERFISH_CCFQuery Args : %s", str(exec_params))
        region_list =  exec_params.region # rarg["region"]
        #
        mfish_ccf_df = pd.read_csv(self.ccf_meta_file)
        _, _, region_frac_map = region_ccf_cell_types(mfish_ccf_df, region_list)
        return [
            {rx: rdf.to_dict(orient="index") for rx, rdf in region_frac_map.items()}
        ]

    @override
    @classmethod
    def params_type(cls) -> type[CCFParamsBase]:
        return cls.QryParams

    @override
    @classmethod
    def params_instance(cls, param_dict: dict[str, t.Any]) -> CCFParamsBase:
        return cls.QryParams.model_validate(param_dict)


class DFBuilder:
    @staticmethod
    def has_sub_region(region_dct: dict[str, t.Any]) -> bool:
        return any(
            isinstance(subregion_dct, collections.abc.Mapping)
            for subregion_dct in region_dct.values()
        )

    @staticmethod
    def qry2dict(
        in_iter: QryItr,
    ) -> list[dict[str, t.Any]]:
        subr_stats = []
        for qry_result in in_iter:
            for _rx, region_dct in qry_result.items():
                if DFBuilder.has_sub_region(region_dct):
                    for subregion_dct in region_dct.values():
                        subr_stats.append(subregion_dct)
                else:
                    subr_stats.append(region_dct)
        return subr_stats

    @staticmethod
    def build(
        in_iter: QryItr | None,
        **_params: t.Any,
    ) -> pl.DataFrame | None:
        if in_iter is None:
            return None
        return pl.DataFrame(DFBuilder.qry2dict(in_iter))


class ABCDuckDBWriter(QryDBWriter):
    def __init__(self, db_conn: duckdb.DuckDBPyConnection):
        self.conn : duckdb.DuckDBPyConnection = db_conn

    @override
    def write(
        self,
        in_iter: QryItr | None,
        **_params: t.Any,
    ) -> None:
        result_df = DFBuilder.build(in_iter) # pyright: ignore[reportUnusedVariable]
        self.conn.execute(
            "CREATE OR REPLACE TABLE abm_mouse AS SELECT * FROM result_df"
        )
        self.conn.commit()
