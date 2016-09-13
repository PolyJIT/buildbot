import sys

from polyjit.buildbot.builders import register
from polyjit.buildbot import slaves
from polyjit.buildbot.utils import (builder, define, git, cmd, trigger, ip,
                                    mkdir, s_sbranch, s_force, s_trigger,
                                    hash_download_from_master, clean_unpack)
from polyjit.buildbot.repos import make_cb, codebases
from buildbot.plugins import util
from buildbot.changes import filter

codebase = make_cb(['benchbuild'])

P = util.Property
BuildFactory = util.BuildFactory


def has_munged(host):
    if "has_munged" in host["properties"]:
        return host["properties"]["has_munged"]
    return False


def can_build_llvm(host):
    if "can_build_llvm_debug" in host["properties"]:
        return host["properties"]["can_build_llvm_debug"]
    return False


def has_munged_and_can_build_llvm(host):
    return has_munged(host) and can_build_llvm(host)

accepted_builders = slaves.get_hostlist(slaves.infosun,
                                        predicate=has_munged_and_can_build_llvm)


# yapf: disable
def configure(c):
    steps = [
#        trigger(schedulerNames=['trigger-build-llvm', 'trigger-build-jit']),
        define("scratch", ip("/scratch/pjtest/debug-%(prop:buildnumber)s/"))
    ]
    steps.extend(clean_unpack("llvm-debug.tar.gz", "llvm"))
    steps.extend(clean_unpack("polyjit-debug.tar.gz", "polyjit"))
    steps.extend([
        define("BENCHBUILD_ROOT", ip("%(prop:builddir)s/build/benchbuild/")),
        git('benchbuild', 'develop', codebases, workdir=P("BENCHBUILD_ROOT")),

    ])

    steps.extend([
        define('benchbuild', ip('%(prop:scratch)s/env/bin/benchbuild')),
        define('llvm', ip('%(prop:scratch)s/llvm')),
        define('polyjit', ip('%(prop:scratch)s/polyjit')),

        mkdir(P("scratch")),
        cmd('virtualenv', '-ppython3', ip('%(prop:scratch)s/env/')),
        cmd(ip('%(prop:scratch)s/env/bin/pip3'), 'install', '--upgrade', '.',
            workdir='build/benchbuild'),
        cmd("rsync", "-var", "llvm", P("scratch")),
        cmd("rsync", "-var", "polyjit", P("scratch")),
        cmd(P('benchbuild'), 'bootstrap', '-s', env={
                'BB_TMP_DIR': '/scratch/pjtest/src/',
                'BB_TEST_DIR': P("testinputs"),
                'BB_GENTOO_HTTP_PROXY': 'debussy.fim.uni-passau.de:3128',
                'BB_GENTOO_FTP_PROXY': 'debussy.fim.uni-passau.de:3128',
                'BB_GENTOO_AUTOTEST_LOC': '/scratch/pjtest/gentoo-autotest',
                'BB_DB_HOST': 'debussy.fim.uni-passau.de',
                'BB_DB_USER': 'bb',
                'BB_DB_PASS': 'bb',
                'BB_DB_NAME': 'pprof-bb',
                'BB_SLURM_PARTITION': 'chimaira',
                'BB_SLURM_NODE_DIR': '/local/hdd/pjtest/',
                'BB_SLURM_ACCOUNT': 'cl',
                'BB_SLURM_TIMELIMIT': '24:00:00',
                'BB_ENV_COMPILER_PATH': ip('["%(prop:llvm)s/bin", "%(prop:polyjit)s/bin"]'),
                'BB_ENV_COMPILER_LD_LIBRARY_PATH':
                    ip('["%(prop:llvm)s/lib", "%(prop:polyjit)s/lib"]'),
                'BB_ENV_BINARY_PATH': ip('["%(prop:llvm)s/bin", "%(prop:polyjit)s/bin"]'),
                'BB_ENV_BINARY_LD_LIBRARY_PATH':
                    ip('["%(prop:llvm)s/lib", "%(prop:polyjit)s/lib"]'),
                'BB_ENV_LOOKUP_PATH':
                    ip('["%(prop:llvm)s/bin", "%(prop:polyjit)s/bin", "/scratch/pjtest/erlent/build"]'),
                'BB_ENV_LOOKUP_LD_LIBRARY_PATH':
                    ip('["%(prop:llvm)s/lib", "%(prop:polyjit)s/lib"]'),
                'BB_LLVM_DIR': ip('%(prop:scratch)s/llvm'),
                'BB_LIKWID_PREFIX': '/usr',
                'BB_PAPI_INCLUDE': '/usr/include',
                'BB_PAPI_LIBRARY': '/usr/lib',
                'BB_SRC_DIR': ip('%(prop:scratch)s/benchbuild'),
                'BB_SLURM_LOGS': ip('%(prop:scratch)s/slurm.log'),
                'BB_UNIONFS_ENABLE': 'false'
            },
            workdir=P('scratch')),
        mkdir(ip("%(prop:scratch)s/results"))])

    c['builders'].append(builder("build-slurm-set-debug", None, accepted_builders,
        factory=BuildFactory(steps)))
# yapf: enable

def schedule(c):
    c['schedulers'].extend([
        s_sbranch("build-slurm-set-debug-sched", codebase, ["build-slurm-set-debug"],
                  change_filter=filter.ChangeFilter(branch_re='next|develop'),
                  treeStableTimer=2 * 60),
        s_force("force-build-slurm-set-debug", codebase, ["build-slurm-set-debug"]),
        s_trigger("trigger-slurm-set-debug", codebase, ['build-slurm-set-debug'])
    ])


register(sys.modules[__name__])
