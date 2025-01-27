# Quick install scripts

`bash/` contains simple bash scripts to automate some of the installation of **riboviz**'s dependencies. They are the manual commands of [Install riboviz and dependencies](./install.md) in bash script form.

These scripts were written for Ubuntu 18.04 and CentOS 7.4.

Running these scripts requires you to have permission to run `sudo` to install and configure software. If you don't have `sudo` access you will have to ask a local system administrator to run these commands for you.

**Note:** These scripts are not robust and do not perform any error handling.

Authenticate with `sudo`:

```console
$ sudo su -
CTRL-D
```

Install operating system packages and R:

* Ubuntu:

```console
$ source bash/install-ubuntu.sh
```

* CentOS:

```console
$ source bash/install-centos.sh
```

Install R packages:

```console
$ Rscript rscripts/install_r.R
```

Check that R's library paths include your personal library:

```console
$ Rscript -e ".libPaths()"
```

You should see something like:

* Ubuntu:

```
[1] "/home/ubuntu/R/x86_64-pc-linux-gnu-library/3.4"
[2] "/usr/local/lib/R/site-library"                 
[3] "/usr/lib/R/site-library"                       
[4] "/usr/lib/R/library"     
```

* CentOS:

```
[1] "/home/centos/R/x86_64-redhat-linux-gnu-library/3.5"
[2] "/usr/lib64/R/library"                              
[3] "/usr/share/R/library"  
```

Install Miniconda Python 3 and Python packages:

```console
$ source bash/install-py.sh
```

Install Hisat2 and Bowtie:

```console
$ source bash/install-tools.sh
```

Create `set-riboviz-env.sh`:

```console
$ source bash/create-set-riboviz-env.sh
```
