"""
:py:mod:`riboviz.tools.prep_riboviz` regression test suite.

The regression test suite runs :py:mod:`riboviz.tools.prep_riboviz`
or :py:const:`riboviz.test.NEXTFLOW_WORKFLOW` (via Nextflow) using a
given configuration file, then compares the results to a directory of
pre-calculated results, specified by the user.

Usage::

    pytest riboviz/test/regression/test_regression.py
      --expected=DIRECTORY
      [--skip-workflow]
      [--check-index-tmp]
      [--config-file=FILE]
      [--nextflow]

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
* ``--nextflow``: Run :py:const:`riboviz.test.NEXTFLOW_WORKFLOW` (via
  Nextflow). Note that some regression tests differ for Nextflow due
  to differences in naming of some temporary files.

If the configuration uses environment variable tokens:

* :py:const:`riboviz.params.ENV_RIBOVIZ_SAMPLES`
* :py:const:`riboviz.params.ENV_RIBOVIZ_ORGANISMS`
* :py:const:`riboviz.params.ENV_RIBOVIZ_DATA`

then these should be defined in the bash shell within which ``pytest``
is run. Alternatively, they can be provided when running ``pytest``,
for example::

    $ RIBOVIZ_SAMPLES=data/ RIBOVIZ_ORGANISMS=vignette/input/ \
      RIBOVIZ_DATA=data/ pytest ...

If the configuration specifies samples
(:py:const:`riboviz.params.FQ_FILES`) then ``--check-index-tmp``
can be used.

If the configuration specifies multiplexed samples
(:py:const:`riboviz.params.MULTIPLEX_FQ_FILES`) then
``--check-index-tmp`` cannot be used. This regression test module
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

See :py:mod:`riboviz.test.regression.conftest` for information on the
fixtures used by these tests.
"""
import os
import pytest
import pysam
from riboviz import environment
from riboviz import h5
from riboviz import hisat2
from riboviz import sam_bam
from riboviz import compare_files
from riboviz import count_reads
from riboviz import workflow_files
from riboviz import workflow_r
from riboviz.tools import prep_riboviz
from riboviz.test import nextflow
from riboviz import test


@pytest.fixture(scope="module")
def prep_riboviz_fixture(skip_workflow_fixture, config_fixture,
                         nextflow_fixture):
    """
    Run :py:mod:`riboviz.tools.prep_riboviz` if
    ``skip_workflow_fixture`` is not ``True``.

    :param skip_workflow_fixture: Should workflow not be run?
    :type skip_workflow_fixture: bool
    :param config_fixture: Configuration file
    :type config_fixture: str or unicode
    :param nextflow_fixture: Should Nextflow be run?
    :type nextflow_fixture: bool
    """
    if not skip_workflow_fixture:
        if not nextflow_fixture:
            exit_code = prep_riboviz.prep_riboviz(config_fixture)
        else:
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
    :type tmpdir py._path.local.LocalPath
    :return: directory
    :rtype: py._path.local.LocalPath
    """
    return tmpdir.mkdir("scratch")


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("index", list(range(1, test.NUM_INDICES)))
def test_hisat2_build_index(expected_fixture, index_dir, index_prefix,
                            index):
    """
    Test ``hisat2-build`` index files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param index_dir: Index files directory, from configuration file
    :type index_dir: str or unicode
    :param index_prefix: Index file name prefix
    :type index_prefix: str or unicode
    :param index: File name index
    :type index: int
    """
    file_name = hisat2.HT2_FORMAT.format(index_prefix, index)
    index_dir_name = os.path.basename(os.path.normpath(index_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, index_dir_name, file_name),
        os.path.join(index_dir, file_name))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_cutadapt_fq(expected_fixture, tmp_dir, sample):
    """
    Test ``cutadapt`` FASTQ files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.ADAPTER_TRIM_FQ),
        os.path.join(tmp_dir, sample, workflow_files.ADAPTER_TRIM_FQ))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_extract_fq(extract_umis, expected_fixture, tmp_dir,
                             sample):
    """
    Test ``umi_tools extract`` FASTQ files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If UMI extraction was not enabled in the configuration that
    produced the data then this test is skipped.

    :param extract_umi: Was UMI extraction configured?
    :type extract_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    if not extract_umis:
        pytest.skip('Skipped test applicable to UMI extraction')
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.UMI_EXTRACT_FQ),
        os.path.join(tmp_dir, sample, workflow_files.UMI_EXTRACT_FQ))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.NON_RRNA_FQ,
    workflow_files.UNALIGNED_FQ])
def test_hisat_fq(expected_fixture, tmp_dir, sample, file_name):
    """
    Test ``hisat`` FASTQ files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     file_name),
        os.path.join(tmp_dir, sample, file_name))


def compare_sam_files(expected_directory, directory,
                      scratch_directory, sample, file_name):
    """
    Test SAM files for equality. The SAM files are sorted
    into temporary SAM files which are then compared. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_directory: Expected data directory
    :type expected_directory: str or unicode
    :param directory: Data directory
    :type directory: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: sample name
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
    compare_files.compare_files(expected_copy_file, actual_copy_file)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.ORF_MAP_SAM,
    workflow_files.RRNA_MAP_SAM])
def test_hisat2_sam(expected_fixture, tmp_dir, scratch_directory,
                    sample, file_name):
    """
    Test ``hisat`` SAM files for equality. The SAM files are sorted
    into temporary SAM files which are then compared. See
    :py:func:`compare_sam_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    compare_sam_files(expected_fixture, tmp_dir, scratch_directory,
                      sample, file_name)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_trim5p_mismatch_sam(expected_fixture, tmp_dir,
                             scratch_directory, sample):
    """
    Test :py:mod:`riboviz.tools.trim_5p_mismatch` SAM files for
    equality. The SAM files are sorted into temporary SAM files which
    are then compared. See
    :py:func:`compare_files.compare_sam_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param scratch_directory: scratch files directory
    :type scratch_directory: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    compare_sam_files(expected_fixture, tmp_dir, scratch_directory,
                      sample, workflow_files.ORF_MAP_CLEAN_SAM)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_trim5p_mismatch_tsv(expected_fixture, tmp_dir, sample):
    """
    Test :py:mod:`riboviz.tools.trim_5p_mismatch` TSV files for
    equality. See :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.TRIM_5P_MISMATCH_TSV),
        os.path.join(tmp_dir, sample,
                     workflow_files.TRIM_5P_MISMATCH_TSV))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_view_sort_index_pre_dedup_bam(
        dedup_umis, expected_fixture, tmp_dir, sample,
        nextflow_fixture):
    """
    Test ``samtools view | samtools sort`` BAM and ``samtools index``
    BAI files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If UMI deduplication was not enabled in the configuration that
    produced the data then this test is skipped.

    If Nextflow tests were requested then this test is skipped.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param nextflow_fixture: Should Nextflow tests be run?
    :type nextflow_fixture: bool
    """
    if not dedup_umis:
        pytest.skip('Skipped test applicable to UMI deduplication')
    if nextflow_fixture:
        pytest.skip('Skipped test not applicable to Nextflow')
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.PRE_DEDUP_BAM),
        os.path.join(tmp_dir, sample, workflow_files.PRE_DEDUP_BAM))
    bai_file_name = sam_bam.BAI_FORMAT.format(workflow_files.PRE_DEDUP_BAM)
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     bai_file_name),
        os.path.join(tmp_dir, sample, bai_file_name))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_view_sort_index_orf_map_clean_bam(
        expected_fixture, tmp_dir, sample, nextflow_fixture):
    """
    Test ``samtools view | samtools sort`` BAM and ``samtools index``
    BAI files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If Nextflow tests were requested then this test is run.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param nextflow_fixture: Should Nextflow tests be run?
    :type nextflow_fixture: bool
    """
    if not nextflow_fixture:
        pytest.skip('Skipped test applicable to Nextflow only')
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.ORF_MAP_CLEAN_BAM),
        os.path.join(tmp_dir, sample, workflow_files.ORF_MAP_CLEAN_BAM))
    bai_file_name = sam_bam.BAI_FORMAT.format(workflow_files.ORF_MAP_CLEAN_BAM)
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     bai_file_name),
        os.path.join(tmp_dir, sample, bai_file_name))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_index_dedup_bam(dedup_umis, tmp_dir, sample,
                                  nextflow_fixture):
    """
    Test ``samtools index`` BAI files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If UMI deduplication was not enabled in the configuration that
    produced the data then this test is skipped.

    If Nextflow tests were requested then this test is run.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param nextflow_fixture: Should Nextflow tests be run?
    :type nextflow_fixture: bool
    """
    if not dedup_umis:
        pytest.skip('Skipped test applicable to UMI deduplication')
    if not nextflow_fixture:
        pytest.skip('Skipped test applicable to Nextflow only')
    assert os.path.exists(os.path.join(tmp_dir, sample,
                                       workflow_files.DEDUP_BAM))
    assert os.path.exists(os.path.join(
        tmp_dir, sample, sam_bam.BAI_FORMAT.format(workflow_files.DEDUP_BAM)))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_samtools_view_sort_index(dedup_umis, expected_fixture,
                                  output_dir, sample):
    """
    Test ``samtools view | samtools sort`` BAM and ``samtools index``
    BAI files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If UMI deduplication was enabled in the configuration that
    produced the data then the only the existence of the files are
    checked as these files can differ between runs depending on which
    reads are removed by ``umi_tools dedup``.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    file_name = sam_bam.BAM_FORMAT.format(sample)
    bai_file_name = sam_bam.BAI_FORMAT.format(file_name)
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(
        expected_fixture, output_dir_name, sample, file_name)
    expected_bai_file = os.path.join(
        expected_fixture, output_dir_name, sample, bai_file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    actual_file = os.path.join(output_dir, sample, file_name)
    actual_bai_file = os.path.join(output_dir, sample, bai_file_name)
    assert os.path.exists(actual_file)
    assert os.path.exists(actual_bai_file)
    if dedup_umis:
        return
    compare_files.compare_files(expected_file, actual_file)
    compare_files.compare_files(expected_bai_file, actual_bai_file)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("stats_file", ["edit_distance.tsv",
                                        "per_umi_per_position.tsv",
                                        "per_umi.tsv"])
def test_umitools_dedup_stats_tsv(
        dedup_umis, dedup_stats, expected_fixture, tmp_dir,
        sample, stats_file):
    """
    Test ``umi_tools dedup --output-stats`` TSV files exist.

    If UMI deduplication was not enabled in the configuration that
    produced the data then this test is skipped.

    If UMI deduplication statistics were not enabled in the
    configuration that produced the data then this test is skipped.

    As these files can differ between runs depending on which reads
    are removed by ``umi_tools dedup``, only the existence of the
    files is checked.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param dedup_stats: Were UMI deduplication statistics enabled?
    :type dedup_stats: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param stats_file: statistics file name
    :type stats_file: str or unicode
    """
    if not dedup_umis:
        pytest.skip('Skipped test applicable to UMI deduplication')
    if not dedup_stats:
        pytest.skip('Skipped test applicable to UMI deduplication statistics')
    file_name = os.path.join(sample,
                             workflow_files.DEDUP_STATS_FORMAT.format(
                                 stats_file))
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    expected_file = os.path.join(expected_fixture, tmp_dir_name,
                                 file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    actual_file = os.path.join(tmp_dir, file_name)
    assert os.path.exists(actual_file)


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_pre_dedup_group_tsv(
        group_umis, expected_fixture, tmp_dir, sample):
    """
    Test ``umi_tools group`` TSV files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    If UMI grouping was not enabled in the configuration that
    produced the data then this test is skipped.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    if not group_umis:
        pytest.skip('Skipped test applicable to UMI groups')
    tmp_dir_name = os.path.basename(os.path.normpath(tmp_dir))
    compare_files.compare_files(
        os.path.join(expected_fixture, tmp_dir_name, sample,
                     workflow_files.PRE_DEDUP_GROUPS_TSV),
        os.path.join(tmp_dir, sample,
                     workflow_files.PRE_DEDUP_GROUPS_TSV))


@pytest.mark.usefixtures("skip_index_tmp_fixture")
@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_umitools_post_dedup_group_tsv(group_umis, tmp_dir, sample):
    """
    Test ``umi_tools group`` TSV files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    As these files can differ between runs depending on which reads
    are removed by ``umi_tools dedup``, only the existence of the file
    is checked.

    If UMI grouping was not enabled in the configuration that
    produced the data then this test is skipped.

    :param dedup_umi: Was UMI deduplication configured?
    :type dedup_umis: bool
    :param tmp_dir: Temporary directory, from configuration file
    :type tmp_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    if not group_umis:
        pytest.skip('Skipped test applicable to UMI groups')
    assert os.path.exists(
        os.path.join(tmp_dir, sample, workflow_files.POST_DEDUP_GROUPS_TSV))


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name", [
    workflow_files.MINUS_BEDGRAPH,
    workflow_files.PLUS_BEDGRAPH])
def test_bedtools_bedgraph(expected_fixture, output_dir, sample,
                           file_name):
    """
    Test ``bedtools genomecov`` bedgraph files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(expected_fixture, output_dir_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    compare_files.compare_files(
        expected_file,
        os.path.join(output_dir, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_bam_to_h5_h5(expected_fixture, output_dir, sample):
    """
    Test ``bam_to_h5.R`` H5 files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    """
    file_name = h5.H5_FORMAT.format(sample)
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(expected_fixture, output_dir_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    compare_files.compare_files(
        expected_file,
        os.path.join(output_dir, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name",
                         [workflow_r.THREE_NT_PERIODICITY_TSV,
                          workflow_r.CODON_RIBODENS_TSV,
                          workflow_r.POS_SP_NT_FREQ_TSV,
                          workflow_r.POS_SP_RPF_NORM_READS_TSV,
                          workflow_r.READ_LENGTHS_TSV,
                          workflow_r.THREE_NT_FRAME_BY_GENE_TSV,
                          workflow_r.TPMS_TSV])
def test_generate_stats_figs_tsv(expected_fixture, output_dir, sample,
                                 file_name):
    """
    Test ``generate_stats_figs.R`` TSV files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(expected_fixture, output_dir_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    compare_files.compare_files(
        expected_file,
        os.path.join(output_dir, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
@pytest.mark.parametrize("file_name",
                         [workflow_r.THREE_NT_PERIODICITY_PDF,
                          workflow_r.CODON_RIBODENS_PDF,
                          workflow_r.FEATURES_PDF,
                          workflow_r.POS_SP_RPF_NORM_READS_PDF,
                          workflow_r.READ_LENGTHS_PDF,
                          workflow_r.START_CODON_RIBOGRID_BAR_PDF,
                          workflow_r.START_CODON_RIBOGRID_PDF,
                          workflow_r.THREE_NT_FRAME_PROP_BY_GENE_PDF])
def test_generate_stats_figs_pdf(expected_fixture, output_dir, sample,
                                 file_name):
    """
    Test ``generate_stats_figs.R`` PDF files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    :param sample: sample name
    :type sample: str or unicode
    :param file_name: file name
    :type file_name: str or unicode
    """
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(expected_fixture, output_dir_name,
                                 sample, file_name)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    compare_files.compare_files(
        expected_file,
        os.path.join(output_dir, sample, file_name))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_collate_tpms_tsv(expected_fixture, output_dir):
    """
    Test ``collate_tpms.R`` TSV files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    Test non-sample-specific output TSV files for equality. See
    :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    """
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    expected_file = os.path.join(expected_fixture, output_dir_name,
                                 workflow_r.TPMS_COLLATED_TSV)
    if not os.path.exists(expected_file):
        pytest.skip('Skipped as expected file does not exist')
    compare_files.compare_files(
        expected_file,
        os.path.join(output_dir, workflow_r.TPMS_COLLATED_TSV))


@pytest.mark.usefixtures("prep_riboviz_fixture")
def test_read_counts_tsv(expected_fixture, output_dir):
    """
    Test :py:mod:`riboviz.tools.count_reads` TSV files for
    equality. See :py:func:`riboviz.compare_files.compare_files`.

    :param expected_fixture: Expected data directory
    :type expected_fixture: str or unicode
    :param output_dir: Output directory, from configuration file
    :type output_dir: str or unicode
    """
    output_dir_name = os.path.basename(os.path.normpath(output_dir))
    count_reads.equal_read_counts(
        os.path.join(expected_fixture, output_dir_name,
                     workflow_files.READ_COUNTS_FILE),
        os.path.join(output_dir, workflow_files.READ_COUNTS_FILE))
