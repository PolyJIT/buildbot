import sys

from polyjit.buildbot.builders import register
from polyjit.buildbot import slaves
from polyjit.buildbot.utils import (builder, define, git, ucmd, ucompile, cmd,
                                    upload_file, ip, s_sbranch,
                                    s_nightly, s_force, s_trigger,
                                    hash_upload_to_master)
from polyjit.buildbot.repos import make_cb, make_new_cb, codebases
from polyjit.buildbot.master import URL
from buildbot.plugins import util
from buildbot.changes import filter

codebase = make_cb(['llvm', 'clang', 'polly', 'openmp', 'compiler-rt'])
force_codebase = make_new_cb(['llvm', 'clang', 'polly', 'openmp', 'compiler-rt'])

P = util.Property
BuildFactory = util.BuildFactory
accepted_builders = slaves.get_hostlist(slaves.infosun)


# yapf: disable
def configure(c):
    steps = [
        define("LLVM_ROOT", ip("%(prop:builddir)s/llvm")),
        define("UCHROOT_SRC_ROOT", "/mnt/llvm"),
        define("CLANG_ROOT", ip("%(prop:LLVM_ROOT)s/tools/clang")),
        define("POLLY_ROOT", ip("%(prop:LLVM_ROOT)s/tools/polly")),
        define("COMPILERRT_ROOT", ip("%(prop:LLVM_ROOT)s/projects/compiler-rt")),
        define("OPENMP_ROOT", ip("%(prop:LLVM_ROOT)s/projects/openmp")),

        git('llvm', 'master', codebases, workdir=P("LLVM_ROOT")),
        git('clang', 'master', codebases, workdir=P("CLANG_ROOT")),
        git('polly', 'master', codebases, workdir=P("POLLY_ROOT")),
        git('compiler-rt', 'master', codebases, workdir=P("COMPILERRT_ROOT")),
        git('openmp', 'master', codebases, workdir=P("OPENMP_ROOT")),
        ucmd('cmake', P("UCHROOT_SRC_ROOT"),
             '-DCMAKE_BUILD_TYPE=Release',
             '-DCMAKE_INSTALL_PREFIX=./_install',
             '-DCMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG -DLLVM_ENABLE_STATS',
             '-DBUILD_SHARED_LIBS=Off',
             '-DPOLLY_BUILD_POLLI=Off',
             '-DLLVM_POLLY_LINK_INTO_TOOLS=OFF',
             '-DLLVM_TARGETS_TO_BUILD=X86',
             '-DLLVM_BINUTILS_INCDIR=/usr/include',
             '-DLLVM_ENABLE_PIC=On',
             '-DLLVM_ENABLE_ASSERTIONS=On',
             '-DLLVM_ENABLE_TERMINFO=Off',
             '-DCLANG_DEFAULT_OPENMP_RUNTIME=libomp',
             '-G', 'Ninja',
             env={
                 "PATH": "/opt/cmake/bin:/usr/local/bin:/usr/bin:/bin"
             },
             name="cmake",
             description="cmake O3, Assertions, PIC, Static"),
        ucompile("ninja", "install", haltOnFailure=True, name="build llvm"),
        cmd("tar", "czf", "../llvm.tar.gz", "-C", "./_install", ".")
    ]
    upload_llvm = hash_upload_to_master("llvm.tar.gz",
        "../llvm.tar.gz", "public_html/llvm.tar.gz", URL)
    steps.extend(upload_llvm)

    c['builders'].append(builder("build-llvm", None, accepted_builders,
                         tags=['polyjit'], factory=BuildFactory(steps)))

def schedule(c):
    c['schedulers'].extend([
        s_sbranch("build-llvm-sched", codebase, ["build-llvm"], branch="master",
                  treeStableTimer=2*60),
        s_force("force-build-llvm", force_codebase, ["build-llvm"]),
        s_trigger("trigger-build-llvm", codebase, ['build-llvm']),
        s_nightly("nightly-sched-build-llvm", codebase,
                  ["build-llvm"],
                  hour=20, minute=0)
    ])
# yapf: enable


# register(sys.modules[__name__])
