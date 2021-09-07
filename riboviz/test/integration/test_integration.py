"""
Integration test suite.

The integration test suite runs
:py:const:`riboviz.test.NEXTFLOW_WORKFLOW` (via Nextflow) using a
given configuration file, then compares the results to a directory of
pre-calculated results, specified by the user.

Usage::

    pytest riboviz/test/integration/test_integration.py
      --expected=DIRECTORY
      [--skip-workflow]
      [--check-index-tmp]
      [--config-file=FILE]

The test suite accepts the following command-line parameters:

* ``--expected``: Directory with expected data files, against which
  files specified in the configuration file (see below) will be
  checked.
* ``--skip-workflow``: Workflow will not be run prior to checking data
  files. This can be used to check existing files generated by a run
  of the workflow.
* ``--check-index-tmp``: Check index and temporary files (default is
  that only the output files are checked).
* ``--config-file``: Configuration file. If provided then the index,
  temporary and output directories specified in this file will be
  validated against those specified by ``--expected``. If not provided
  then the file :py:const:`riboviz.test.VIGNETTE_CONFIG` will be
  used.

If the configuration uses environment variable tokens, then these
should be defined in the bash shell within which ``pytest`` is
run. Alternatively, they can be provided when running ``pytest``, for
example::

    $ RIBOVIZ_SAMPLES=data/ RIBOVIZ_ORGANISMS=vignette/input/ \
      RIBOVIZ_DATA=data/ pytest ...

If the configuration specifies samples
(:py:const:`riboviz.params.FQ_FILES`) then ``--check-index-tmp``
can be used.

If the configuration specifies multiplexed samples
(:py:const:`riboviz.params.MULTIPLEX_FQ_FILES`) then
``--check-index-tmp`` cannot be used. This integration test module
does not implement support for validating temporary files produced
for worklows including demultiplexing. For sample-specific output
files, each sample-specific output file is only validated if the
directory with the expected results has a corresponding output file
for the sample. This is because the sample names for the tests are
derived from the sample sheet file
(:py:const:`riboviz.params.SAMPLE_SHEET`) and it can't be
guaranteed that a sample in the sample sheet will yield
corresponding sample files post-demultiplexing.

As the expected data directories and those with the data to be tested
may vary in their paths the following approach is used:

* The paths of the directories with the data to be tested are taken to
  be those specified in the configuration file.
* The paths of the directories with the expected data are taken to be
  relative to the ``--expected`` directory and to share common names
  with the final directories of each path of the actual data
  directories.

For example, if the configuration file has::

    dir_index: vignette/index
    dir_out: vignette/simdata_umi_output
    dir_tmp: vignette/simdata_umi_tmp

and ``--expected`` is ``/home/user/simdata-umi-data`` then directories
with the data to be tested are::

    vignette/index
    vignette/simdata_umi_output
    vignette/simdata_umi_tmp

and the directories with the expected data are::

    /home/user/simdata-umi-data/index
    /home/user/simdata-umi-data/simdata_umi_output
    /home/user/simdata-umi-data/simdata_umi_tmp

If running with a configuration that used UMI extraction,
deduplication and grouping then note that:

* UMI deduplication statistics files (files prefixed
  by :py:const:`riboviz.workflow_files.DEDUP_STATS_PREFIX`) can differ
  between runs depending on which reads are removed by ``umi_tools
  dedup``, so only the existence of the files is checked.
* UMI group file post-deduplication files,
  (:py:const:`riboviz.workflow_files.POST_DEDUP_GROUPS_TSV`) can
  differ between runs depending on which reads are removed by
  ``umi_tools dedup``, so only the existence of the file is checked.
* BAM file output by deduplication (``<SAMPLE>.bam``) can differ
  between runs depending on which reads are removed by ``umi_tools
  dedup``, so only the existence of the file is checked.

See :py:mod:`riboviz.test.integration.conftest` for information on the
fixtures used by these tests.
"""
import os
import pytest
import pysam
from riboviz import bedgraph
from riboviz import count_reads as count_reads_module
from riboviz import environment
from riboviz import fastq
from riboviz import h5
from riboviz import html
from riboviz import hisat2
from riboviz import sam_bam
from riboviz import utils
from riboviz import workflow_files
from riboviz import workflow_r
from riboviz.test import nextflow
from riboviz import test


@pytest.fixture(scope="module")
def prep_riboviz_fixture(skip_workflow_fixture, config_fixture):
    """
    Run :py:const:`riboviz.test.NEXTFLOW_WORKFLOW` (via Nextflow)
    if ``skip_workflow_fixture`` is not ``True``.

    :param skip_workflow_fixture: Should workflow not be run?
    :type skip_workflow_fixture: bool
    :param config_fixture: Configuration file
    :type config_fixture: str or unicode
    """
    if not skip_workflow_fixture:
        env_vars = environment.get_environment_vars()
        exit_code = nextflow.run_nextflow(config_fixture,
                                          envs=env_vars)
        assert exit_code == 0, \
            "prep_riboviz returned non-zero exit code %d" % exit_code


@pytest.fixture(scope="function")
def scratch_directory(tmpdir):
    """
    Create a scratch directory.

    :param tmpdir: Temporary directory (pytest built-in fixture)
    :type tmpdir: py._path.local.LocalPath
    :return: directory
    :rtype: py._path.local.LocalPath
    """
    return tmpdir.mkdir("scratch")


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("index", list(range(1, test.NUM_INDICES)))
def test_hisat2_build_index(build_indices, expected_fixture, dir_index,
                            index_prefix, index):
    """
    Test ``hisat2-build`` index file sizes for equality. See
    :py:func:`riboviz.utils.equal_file_sizes`.

    Skipped if :py:const:`riboviz.params.BUILD_INDICES` is ``false``.

    :param build_indicex: Configuration parameter
    :type build_indices: boolean
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_index: Index files directory
    :type dir_index: str or unicode
    :param index_prefix: Index file name prefix
    :type index_prefix: str or unicode
    :param index: File name index
    :type index: int
    """
    if not build_indices:
        pytest.skip('Skipped test as build_indices: '.format(build_indices))
    file_name = hisat2.HT2_FORMAT.format(index_prefix, index)
    dir_index_name = os.path.basename(os.path.normpath(dir_index))
    utils.equal_file_sizes(
        os.path.join(expected_fixture, dir_index_name, file_name),
        os.path.join(dir_index, file_name))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_cutadapt_fq(expected_fixture, dir_tmp, sample):
    """
    Test ``cutadapt`` FASTQ files for equality. See
    :py:func:`riboviz.fastq.equal_fastq`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    fastq.equal_fastq(os.path.join(expected_fixture, dir_tmp_name, sample,
                                   workflow_files.ADAPTER_TRIM_FQ),
                      os.path.join(dir_tmp, sample,
                                   workflow_files.ADAPTER_TRIM_FQ))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_extract_fq(extract_umis, expected_fixture, dir_tmp,
                             sample):
    """
    Test ``umi_tools extract`` FASTQ files for equality. See
    :py:func:`riboviz.fastq.equal_fastq`.

    If UMI extraction was not enabled in the configuration that
    produced the data then this test is skipped.

    :param extract_umi: Was UMI extraction configured?
    :type extract_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    if not extract_umis:
        pytest.skip('Skipped test applicable to UMI extraction')
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    fastq.equal_fastq(
        os.path.join(expected_fixture, dir_tmp_name, sample,
                     workflow_files.UMI_EXTRACT_FQ),
        os.path.join(dir_tmp, sample, workflow_files.UMI_EXTRACT_FQ))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.NON_RRNA_FQ,
    workflow_files.UNALIGNED_FQ])
def test_hisat_fq(expected_fixture, dir_tmp, sample, file_name):
    """
    Test ``hisat`` FASTQ files for equality. See
    :py:func:`riboviz.fastq.equal_fastq`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    fastq.equal_fastq(os.path.join(expected_fixture, dir_tmp_name, sample,
                                   file_name),
                      os.path.join(dir_tmp, sample, file_name))


def compare_sam_files(expected_directory, directory,
                      scratch_directory, sample, file_name):
    """
    Test SAM files for equality. The SAM files are sorted
    into temporary SAM files which are then compared. See
    :py:func:`riboviz.sam_bam.equal_sam`.

    :param expected_directory: Expected data directory
    :type expected_directory: str or unicode
    :param directory: Data directory
    :type directory: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    dir_name = os.path.basename(os.path.normpath(directory))
    expected_file = os.path.join(
        expected_directory, dir_name, sample, file_name)
    actual_file = os.path.join(directory, sample, file_name)
    expected_copy_dir = os.path.join(scratch_directory, "expected")
    os.mkdir(expected_copy_dir)
    actual_copy_dir = os.path.join(scratch_directory, "actual")
    os.mkdir(actual_copy_dir)
    expected_copy_file = os.path.join(expected_copy_dir, file_name)
    actual_copy_file = os.path.join(actual_copy_dir, file_name)
    pysam.sort("-o", expected_copy_file, expected_file)
    pysam.sort("-o", actual_copy_file, actual_file)
    sam_bam.equal_sam(expected_copy_file, actual_copy_file)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.ORF_MAP_SAM,
    workflow_files.RRNA_MAP_SAM])
def test_hisat2_sam(expected_fixture, dir_tmp, scratch_directory,
                    sample, file_name):
    """
    Test ``hisat`` SAM files for equality. The SAM files are sorted
    into temporary SAM files which are then compared. See
    :py:func:`compare_sam_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    compare_sam_files(expected_fixture, dir_tmp, scratch_directory,
                      sample, file_name)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_trim5p_mismatch_sam(expected_fixture, dir_tmp,
                             scratch_directory, sample):
    """
    Test :py:mod:`riboviz.tools.trim_5p_mismatch` SAM files for
    equality. The SAM files are sorted into temporary SAM files which
    are then compared. See :py:func:`compare_sam_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    compare_sam_files(expected_fixture, dir_tmp, scratch_directory,
                      sample, workflow_files.ORF_MAP_CLEAN_SAM)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_trim5p_mismatch_tsv(expected_fixture, dir_tmp, sample):
    """
    Test :py:mod:`riboviz.tools.trim_5p_mismatch` TSV files for
    equality. See :py:func:`riboviz.utils.equal_tsv`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    utils.equal_tsv(
        os.path.join(expected_fixture, dir_tmp_name, sample,
                     workflow_files.TRIM_5P_MISMATCH_TSV),
        os.path.join(dir_tmp, sample,
                     workflow_files.TRIM_5P_MISMATCH_TSV))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_view_sort_index_orf_map_clean_bam(
        expected_fixture, dir_tmp, sample):
    """
    Test ``samtools view | samtools sort`` BAM and ``samtools index``
    BAI files for equality. See :py:func:`riboviz.sam_bam.equal_bam` and
    :py:func:`riboviz.utils.equal_file_sizes`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    sam_bam.equal_bam(
        os.path.join(expected_fixture, dir_tmp_name, sample,
                     workflow_files.ORF_MAP_CLEAN_BAM),
        os.path.join(dir_tmp, sample,
                     workflow_files.ORF_MAP_CLEAN_BAM))
    bai_file_name = sam_bam.BAI_FORMAT.format(workflow_files.ORF_MAP_CLEAN_BAM)
    utils.equal_file_sizes(
        os.path.join(expected_fixture, dir_tmp_name, sample,
                     bai_file_name),
        os.path.join(dir_tmp, sample, bai_file_name))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_index_dedup_bam(dedup_umis, dir_tmp, sample):
    """
    Test ``samtools index`` BAM and BAI files. Check files exist only.

    If UMI deduplication was not enabled in the configuration that
    produced the data then this test is skipped.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    if not dedup_umis:
        pytest.skip('Skipped test applicable to UMI deduplication')
    actual_file = os.path.join(dir_tmp, sample, workflow_files.DEDUP_BAM)
    assert os.path.exists(actual_file), "Non-existent file: %s" % actual_file
    actual_bai_file = os.path.join(
        dir_tmp, sample, sam_bam.BAI_FORMAT.format(workflow_files.DEDUP_BAM))
    assert os.path.exists(actual_bai_file),\
        "Non-existent file: %s" % actual_bai_file


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_view_sort_index(dedup_umis, expected_fixture,
                                  dir_out, sample):
    """
    Test ``samtools view | samtools sort`` BAM and ``samtools index``
    BAI files for equality. See :py:func:`riboviz.sam_bam.equal_bam`
    and :py:func:`riboviz.utils.equal_file_sizes`.

    If UMI deduplication was enabled in the configuration that
    produced the data then the only the existence of the files are
    checked as these files can differ between runs depending on which
    reads are removed by ``umi_tools dedup``.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    file_name = sam_bam.BAM_FORMAT.format(sample)
    bai_file_name = sam_bam.BAI_FORMAT.format(file_name)
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(
        expected_fixture, dir_out_name, sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    actual_file = os.path.join(dir_out, sample, file_name)
    assert os.path.exists(actual_file), "Non-existent file: %s" % actual_file
    expected_bai_file = os.path.join(
        expected_fixture, dir_out_name, sample, bai_file_name)
    actual_bai_file = os.path.join(dir_out, sample, bai_file_name)
    assert os.path.exists(actual_bai_file),\
        "Non-existent file: %s" % actual_bai_file
    if dedup_umis:
        return
    sam_bam.equal_bam(expected_file, actual_file)
    utils.equal_file_sizes(expected_bai_file, actual_bai_file)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("stats_file", ["edit_distance.tsv",
                                        "per_umi_per_position.tsv",
                                        "per_umi.tsv"])
def test_umitools_dedup_stats_tsv(
        dedup_umis, dedup_stats, expected_fixture, dir_tmp,
        sample, stats_file):
    """
    Test ``umi_tools dedup --output-stats`` TSV files exist.

    As these files can differ between runs depending on which reads
    are removed by ``umi_tools dedup``, only the existence of the
    files is checked.

    Skipped if :py:const:`riboviz.params.DEDUP_UMIS` is ``false``
    or :py:const:`riboviz.params.DEDUP_STATS` is ``false``.

    :param dedup_umi: Configuration parameter
    :type dedup_umis: bool
    :param dedup_stats: Configuration parameter
    :type dedup_stats: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param stats_file: statistics file name
    :type stats_file: str or unicode
    """
    if not dedup_umis:
        pytest.skip('Skipped test as dedup_umis: '.format(dedup_umis))
    if not dedup_stats:
        pytest.skip('Skipped test as dedup_stats: '.format(dedup_stats))
    file_name = os.path.join(sample,
                             workflow_files.DEDUP_STATS_FORMAT.format(
                                 stats_file))
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    expected_file = os.path.join(expected_fixture, dir_tmp_name,
                                 file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    actual_file = os.path.join(dir_tmp, file_name)
    assert os.path.exists(actual_file), "Non-existent file: %s" % actual_file


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_pre_dedup_group_tsv(
        dedup_umis, group_umis, expected_fixture, dir_tmp, sample):
    """
    Test ``umi_tools group`` TSV files for equality. See
    :py:func:`riboviz.utils.equal_tsv`.

    Skipped if :py:const:`riboviz.params.DEDUP_UMIS` is ``false``
    or :py:const:`riboviz.params.GROUP_UMIS` is ``false``.

    :param dedup_umis: Configuration parameter
    :type dedup_umis: bool
    :param group_umis: Configuration parameter
    :type group_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    if not dedup_umis:
        pytest.skip('Skipped test as dedup_umis: '.format(dedup_umis))
    if not group_umis:
        pytest.skip('Skipped test as group_umis: '.format(group_umis))
    dir_tmp_name = os.path.basename(os.path.normpath(dir_tmp))
    utils.equal_tsv(
        os.path.join(expected_fixture, dir_tmp_name, sample,
                     workflow_files.PRE_DEDUP_GROUPS_TSV),
        os.path.join(dir_tmp, sample,
                     workflow_files.PRE_DEDUP_GROUPS_TSV))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_post_dedup_group_tsv(
        dedup_umis, group_umis, dir_tmp, sample):
    """
    Test ``umi_tools group`` TSV file exists.

    As these files can differ between runs depending on which reads
    are removed by ``umi_tools dedup``, only the existence of the file
    is checked.

    Skipped if :py:const:`riboviz.params.DEDUP_UMIS` is ``false``
    or :py:const:`riboviz.params.GROUP_UMIS` is ``false``.

    :param dedup_umis: Configuration parameter
    :type dedup_umis: bool
    :param group_umis: Configuration parameter
    :type group_umis: bool
    :param dir_tmp: Temporary directory
    :type dir_tmp: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    if not dedup_umis:
        pytest.skip('Skipped test as dedup_umis: '.format(dedup_umis))
    if not group_umis:
        pytest.skip('Skipped test as group_umis: '.format(group_umis))
    actual_file = os.path.join(
        dir_tmp, sample, workflow_files.POST_DEDUP_GROUPS_TSV)
    assert os.path.exists(actual_file), "Non-existent file: %s" % actual_file


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.MINUS_BEDGRAPH,
    workflow_files.PLUS_BEDGRAPH])
def test_bedtools_bedgraph(expected_fixture, make_bedgraph, dir_out,
                           sample, file_name):
    """
    Test ``bedtools genomecov`` bedgraph files for equality. See
    :py:func:`riboviz.bedgraph.equal_bedgraph`.

    Skipped if :py:const:`riboviz.params.MAKE_BEDGRAPH` is ``false``.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param make_bedgraph: Configuration parameter
    :type make_bedgraph: bool
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    if not make_bedgraph:
        pytest.skip('Skipped test as make_bedgraph: '.format(make_bedgraph))
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 sample, file_name)
    bedgraph.equal_bedgraph(expected_file,
                            os.path.join(dir_out, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_bam_to_h5_h5(expected_fixture, dir_out, sample):
    """
    Test ``bam_to_h5.R`` H5 files for equality. See
    :py:func:`riboviz.h5.equal_h5`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    """
    file_name = h5.H5_FORMAT.format(sample)
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    h5.equal_h5(expected_file,
                os.path.join(dir_out, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name",
                         [workflow_r.METAGENE_START_STOP_READ_COUNTS_TSV,
                          workflow_r.NORMALIZED_DENSITY_APESITES_PER_CODON_TSV,
                          workflow_r.NT_FREQ_PER_READ_POSITION_TSV,
                          workflow_r.METAGENE_NORMALIZED_PROFILE_START_STOP_TSV,
                          workflow_r.READ_COUNTS_BY_LENGTH_TSV,
                          workflow_r.READ_FRAME_PER_ORF_TSV,
                          workflow_r.READ_FRAME_PER_ORF_FILTERED_TSV,
                          workflow_r.ORF_TPMS_VS_FEATURES_TSV,
                          workflow_r.GENE_POSITION_LENGTH_COUNTS_TSV,
                          workflow_r.NORMALIZED_DENSITY_APESITES_PER_CODON_LONG_TSV,
                          workflow_r.ORF_TPMS_AND_COUNTS_TSV])
def test_generate_stats_figs_tsv(expected_fixture, dir_out, sample,
                                 file_name):
    """
    Test ``generate_stats_figs.R`` TSV files for equality. See
    :py:func:`riboviz.utils.equal_tsv`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    utils.equal_tsv(
        expected_file,
        os.path.join(dir_out, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name",
                         [workflow_r.METAGENE_START_STOP_READ_COUNTS_PDF,
                          workflow_r.NORMALIZED_DENSITY_APESITES_PER_CODON_PDF,
                          workflow_r.ORF_TPMS_VS_FEATURES_PDF,
                          workflow_r.METAGENE_NORMALIZED_PROFILE_START_STOP_PDF,
                          workflow_r.READ_COUNTS_BY_LENGTH_PDF,
                          workflow_r.METAGENE_START_BARPLOT_BY_LENGTH_PDF,
                          workflow_r.METAGENE_START_RIBOGRID_BY_LENGTH_PDF,
                          workflow_r.FRAME_PROPORTIONS_PER_ORF_PDF])
def test_generate_stats_figs_pdf(expected_fixture, dir_out, sample,
                                 file_name, output_pdfs):
    """
    Test ``generate_stats_figs.R`` PDF files exist.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    :param output_pdfs: Whether pdfs will be generated
    :type output_pdfs: bool
    """
    if not output_pdfs:
        pytest.skip('Skipped testing for pdfs as pdfs not generated')
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    actual_file = os.path.join(dir_out, sample, file_name)
    assert os.path.exists(actual_file), "Non-existent file: %s" % actual_file


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [workflow_files.STATIC_HTML_FILE])
def test_analysis_outputs_html(run_static_html, expected_fixture,
                               dir_out, sample, file_name):
    """
    Test ``AnalysisOutputs.Rmd`` html files for equality. See
    :py:func:`riboviz.html.equal_html`.

    Skipped if :py:const:`riboviz.params.RUN_STATIC_HTML` is ``false``.

    :param run_static_html: Configuration parameter
    :type run_static_html: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    :param sample: Sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    if not run_static_html:
        pytest.skip('Skipped test as run_static_html: '.format(run_static_html))
    file_name = workflow_files.STATIC_HTML_FILE.format(sample)
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 sample, file_name)
    assert os.path.exists(os.path.join(dir_out, sample, file_name))
    html.equal_html(expected_file,
                    os.path.join(dir_out, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_collate_orf_tpms_and_counts_tsv(expected_fixture, dir_out):
    """
    Test ``collate_tpms.R`` TSV files for equality. See
    :py:func:`riboviz.utils.equal_tsv`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    """
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    expected_file = os.path.join(expected_fixture, dir_out_name,
                                 workflow_r.TPMS_ALL_CDS_ALL_SAMPLES_TSV)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    utils.equal_tsv(expected_file,
                    os.path.join(dir_out, workflow_r.TPMS_ALL_CDS_ALL_SAMPLES_TSV),
                    ignore_row_order=True,
                    na_to_empty_str=True)


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_read_counts_per_file_tsv(count_reads, expected_fixture, dir_out):
    """
    Test :py:mod:`riboviz.tools.count_reads` TSV files for
    equality. See :py:func:`riboviz.count_reads.equal_read_counts`.

    Skipped if :py:const:`riboviz.params.COUNT_READS` is ``false``.

    :param count_reads: Configuration parameter
    :type count_reads: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param dir_out: Output directory
    :type dir_out: str or unicode
    """
    if not count_reads:
        pytest.skip('Skipped test as count_reads'.format(count_reads))
    dir_out_name = os.path.basename(os.path.normpath(dir_out))
    count_reads_module.equal_read_counts(
        os.path.join(expected_fixture, dir_out_name,
                     workflow_files.READ_COUNTS_PER_FILE_FILE),
        os.path.join(dir_out, workflow_files.READ_COUNTS_PER_FILE_FILE))
