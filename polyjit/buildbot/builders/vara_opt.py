import sys
from collections import OrderedDict

from twisted.internet import defer

from polyjit.buildbot.builders import register
from polyjit.buildbot import slaves
from polyjit.buildbot.utils import (builder, define, git, ucmd, ucompile, cmd,
                                    upload_file, ip, s_sbranch, s_abranch,
                                    s_nightly, s_force, s_trigger)
from polyjit.buildbot.repos import make_git_cb, make_force_cb, codebases
from buildbot.plugins import util, steps
from buildbot.changes import filter
from buildbot.process import buildstep, logobserver
from buildbot.interfaces import IRenderable

################################################################################
# Notes:
#
# Get the values for 'upstream_merge_base' with the following command:
#   - git merge-base origin/vara-60-dev upstream/release_60
################################################################################

UCHROOT_SRC_ROOT = '/mnt/vara-llvm'
CHECKOUT_BASE_DIR = '%(prop:builddir)s/vara-llvm'

# Adapt these values according to build type:
PROJECT_NAME = 'vara-opt'
TRIGGER_BRANCHES = 'vara-dev|vara-60-dev'
UCHROOT_BUILD_DIR = UCHROOT_SRC_ROOT + '/build/opt'
BUILD_SCRIPT = 'build-opt.sh'

# Also adapt these values:
REPOS = OrderedDict()
REPOS['vara-llvm'] = {
    'default_branch': 'vara-60-dev',
    'checkout_dir': CHECKOUT_BASE_DIR,
    'checkout_subdir': '',
    'upstream_remote_url': 'https://git.llvm.org/git/llvm.git/',
    'upstream_merge_base': '089d4c0c490687db6c75f1d074e99c4d42936a50',
}
REPOS['vara-clang'] = {
    'default_branch': 'vara-60-dev',
    'checkout_dir': CHECKOUT_BASE_DIR + '/tools/clang',
    'checkout_subdir': '/tools/clang',
    'upstream_remote_url': 'https://git.llvm.org/git/clang.git/',
    'upstream_merge_base': 'ff0c0d8ab3e316bb6e2741fedb3b545e198eab7a',
}
REPOS['vara'] = {
    'default_branch': 'vara-dev',
    'checkout_dir': CHECKOUT_BASE_DIR + '/tools/VaRA',
    'checkout_subdir': '/tools/VaRA',
}
REPOS['compiler-rt'] = {
    'default_branch': 'release_60',
    'checkout_dir': CHECKOUT_BASE_DIR + '/projects/compiler-rt',
}
REPOS['clang-tools-extra'] = {
    'default_branch': 'release_60',
    'checkout_dir': CHECKOUT_BASE_DIR + '/tools/clang/tools/extra',
}

################################################################################

CODEBASE = make_git_cb(REPOS)
FORCE_CODEBASE = make_force_cb(REPOS)

P = util.Property

ACCEPTED_BUILDERS = slaves.get_hostlist(slaves.infosun, predicate=lambda host: host["host"] in {'ligeti', 'debussy'})

class GenerateMakeCleanCommand(buildstep.ShellMixin, steps.BuildStep):

    def __init__(self, **kwargs):
        kwargs = self.setupShellMixin(kwargs)
        steps.BuildStep.__init__(self, **kwargs)
        self.observer = logobserver.BufferLogObserver()
        self.addLogObserver('stdio', self.observer)

    @defer.inlineCallbacks
    def run(self):
        command = yield self.makeRemoteShellCommand()
        yield self.runCommand(command)

        force_build_clean = None
        if self.hasProperty('options'):
            options = self.getProperty('options')
            force_build_clean = options['force_build_clean']

        if force_build_clean:
            self.build.addStepsAfterCurrentStep([
                define('FORCE_BUILD_CLEAN', 'true'),
                ucompile('ninja', 'clean', name='clean build dir',
                         workdir=UCHROOT_BUILD_DIR, haltOnFailure=True, warnOnWarnings=True)
            ])
        else:
            self.build.addStepsAfterCurrentStep([define('FORCE_BUILD_CLEAN', 'false')])

        defer.returnValue(command.results())

class GenerateGitCloneCommand(buildstep.ShellMixin, steps.BuildStep):

    def __init__(self, **kwargs):
        kwargs = self.setupShellMixin(kwargs)
        steps.BuildStep.__init__(self, **kwargs)
        self.observer = logobserver.BufferLogObserver()
        self.addLogObserver('stdio', self.observer)

    @defer.inlineCallbacks
    def run(self):
        command = yield self.makeRemoteShellCommand()
        yield self.runCommand(command)

        force_complete_rebuild = None
        if self.hasProperty('options'):
            options = self.getProperty('options')
            force_complete_rebuild = options['force_complete_rebuild']

        buildsteps = []

        for repo in REPOS:
            buildsteps.append(define(str(repo).upper() +'_ROOT', ip(REPOS[repo]['checkout_dir'])))

        if force_complete_rebuild:
            buildsteps.append(define('FORCE_COMPLETE_REBUILD', 'true'))
            buildsteps.append(steps.ShellCommand(name='Delete old build directory',
                                                 command=['rm', '-rf', 'build'],
                                                 workdir=ip(CHECKOUT_BASE_DIR)))

            for repo in REPOS:
                if 'repository_clone_url' in codebases[repo].keys():
                    url = codebases[repo]['repository_clone_url']
                else:
                    url = codebases[repo]['repository']
                branch = REPOS[repo]['default_branch']

                buildsteps.append(steps.Git(repourl=url, branch=branch, codebase=repo,
                                            name="checkout: {0}".format(url),
                                            description="checkout: {0}@{1}".format(url, branch),
                                            timeout=1200, progress=True,
                                            workdir=P(str(repo).upper()+'_ROOT'),
                                            mode='full', method='clobber'))
        else:
            self.build.addStepsAfterCurrentStep([define('FORCE_COMPLETE_REBUILD', 'false')])
            for repo in REPOS:
                if 'repository_clone_url' in codebases[repo].keys():
                    url = codebases[repo]['repository_clone_url']
                else:
                    url = codebases[repo]['repository']
                branch = REPOS[repo]['default_branch']

                buildsteps.append(steps.Git(repourl=url, branch=branch, codebase=repo,
                                            name="checkout: {0}".format(url),
                                            description="checkout: {0}@{1}".format(url, branch),
                                            workdir=P(str(repo).upper()+'_ROOT')))

        buildsteps.append(steps.ShellCommand(name='Create build directory',
                                             command=['mkdir', '-p', 'build'],
                                             workdir=ip(CHECKOUT_BASE_DIR), hideStepIf=True))

        self.build.addStepsAfterCurrentStep(buildsteps)

        defer.returnValue(command.results())


class GenerateMergecheckCommand(buildstep.ShellMixin, steps.BuildStep):

    def __init__(self, **kwargs):
        kwargs = self.setupShellMixin(kwargs)
        steps.BuildStep.__init__(self, **kwargs)
        self.observer = logobserver.BufferLogObserver()
        self.addLogObserver('stdio', self.observer)

    @defer.inlineCallbacks
    def run(self):
        command = yield self.makeRemoteShellCommand()
        yield self.runCommand(command)

        result = command.results()
        if result == util.SUCCESS:
            mergecheck_repo = self.getProperty('mergecheck_repo')
            current_branch = self.observer.getStdout().strip()
            #default_branch = REPOS[mergecheck_repo]['default_branch']
            repo_subdir = REPOS[mergecheck_repo]['checkout_subdir']
            upstream_merge_base = ''
            upstream_remote_url = ''

            if ('upstream_merge_base' not in REPOS[mergecheck_repo]
                    or 'upstream_remote_url' not in REPOS[mergecheck_repo]):
                # This repository has no remote to compare against, so no mergecheck has to be done.
                defer.returnValue(result)
            else:
                upstream_merge_base = REPOS[mergecheck_repo]['upstream_merge_base']
                upstream_remote_url = REPOS[mergecheck_repo]['upstream_remote_url']

            self.build.addStepsAfterCurrentStep([
                steps.Compile(
                    command=['/scratch/pjtest/mergecheck/build/bin/mergecheck', 'rebase',
                             '--repo', '.' + repo_subdir,
                             '--remote-url', upstream_remote_url,
                             '--remote-name', 'upstream',
                             '--onto', 'refs/remotes/upstream/master',
                             '--upstream', upstream_merge_base,
                             '--branch', current_branch,
                             '-v', '--print-conflicts',
                            ],
                    workdir=ip(CHECKOUT_BASE_DIR),
                    name='Mergecheck \"' + mergecheck_repo + '\"',
                    warnOnWarnings=False, warningPattern='^CONFLICT.*'),
            ])

            defer.returnValue(result)

# yapf: disable
def configure(c):
    f = util.BuildFactory()

    # TODO Check if this can be done without a dummy command
    #f.addStep(GenerateGitCloneCommand())
    f.addStep(GenerateGitCloneCommand(name="Dummy_1", command=['true'],
                                      haltOnFailure=True, hideStepIf=True))

    f.addStep(define('UCHROOT_SRC_ROOT', UCHROOT_SRC_ROOT))
    f.addStep(define('UCHROOT_BUILD_DIR', UCHROOT_BUILD_DIR))

    f.addStep(ucompile('../tools/VaRA/utils/vara/builds/' + BUILD_SCRIPT,
                       env={'PATH': '/opt/cmake/bin:/usr/local/bin:/usr/bin:/bin'},
                       name='cmake',
                       description=BUILD_SCRIPT,
                       workdir=UCHROOT_SRC_ROOT + '/build'))

    f.addStep(GenerateMakeCleanCommand(name="Dummy_2", command=['true'],
                                       haltOnFailure=True, hideStepIf=True))

    f.addStep(ucompile('ninja', haltOnFailure=True, warnOnWarnings=True, name='build VaRA',
                       workdir=UCHROOT_BUILD_DIR))

    f.addStep(ucompile('ninja', 'check-vara', name='run VaRA regression tests',
                       workdir=UCHROOT_BUILD_DIR,
                       haltOnFailure=False, warnOnWarnings=True))

    # use mergecheck tool to make sure the 'upstream' remote is present
    for repo in ['vara-llvm', 'vara-clang']:
        f.addStep(steps.Compile(
            command=['/scratch/pjtest/mergecheck/build/bin/mergecheck', 'rebase',
                     '--repo', '.' + REPOS[repo]['checkout_subdir'],
                     '--remote-url', REPOS[repo]['upstream_remote_url'],
                     '--remote-name', 'upstream',
                     '--upstream', 'refs/remotes/upstream/master',
                     '--branch', 'refs/remotes/upstream/master',
                     '-v'],
            workdir=ip(CHECKOUT_BASE_DIR),
            name='Add upstream remote to repository.', hideStepIf=True))

    # Clang-Tidy
    f.addStep(ucompile('python3', 'tidy-vara.py', '-p', UCHROOT_BUILD_DIR, '-j', '8', '--gcc',
                       workdir='vara-llvm/tools/VaRA/test/', name='run Clang-Tidy',
                       haltOnFailure=False, warnOnWarnings=True,
                       env={'PATH': ["/mnt/build/bin", "${PATH}"]}, timeout=3600))

    # ClangFormat
    f.addStep(ucompile('bash', 'bb-clang-format.sh', '--cf-binary',
                       UCHROOT_BUILD_DIR + '/bin/clang-format', '--all', '--line-numbers',
                       workdir='vara-llvm/tools/VaRA/utils/buildbot',
                       name='run ClangFormat', haltOnFailure=False, warnOnWarnings=True,
                       env={'PATH': ["/mnt/build/bin", "${PATH}"]}))

    # Mergecheck
    for repo in ['vara-llvm', 'vara-clang', 'vara']:
        f.addStep(define('mergecheck_repo', repo))
        f.addStep(GenerateMergecheckCommand(name="Dummy_3", command=['git', 'symbolic-ref', 'HEAD'],
                                            workdir=ip(REPOS[repo]['checkout_dir']),
                                            haltOnFailure=True, hideStepIf=True))

    c['builders'].append(builder('build-' + PROJECT_NAME, None, ACCEPTED_BUILDERS, tags=['vara'],
                                 factory=f))

def schedule(c):
    force_sched = s_force(
        name="force-build-" + PROJECT_NAME,
        cb=FORCE_CODEBASE,
        builders=["build-" + PROJECT_NAME],
        properties=[
            util.NestedParameter(name="options", label="Build Options", layout="vertical", fields=[
                util.BooleanParameter(name="force_build_clean", label="force a make clean",
                                      default=False),
                util.BooleanParameter(name="force_complete_rebuild",
                                      label="force complete rebuild and fresh git clone",
                                      default=False),
            ])
        ]
    )

    c['schedulers'].extend([
        s_abranch('build-' + PROJECT_NAME + '-sched', CODEBASE, ['build-' + PROJECT_NAME],
                  change_filter=filter.ChangeFilter(branch_re=TRIGGER_BRANCHES),
                  treeStableTimer=5 * 60),
        force_sched,
        s_trigger('trigger-build-' + PROJECT_NAME, CODEBASE, ['build-' + PROJECT_NAME]),
        # TODO: Fix nightly scheduler (currently not working)
        #s_nightly('nightly-sched-build-' + PROJECT_NAME, CODEBASE,
        #          ['build-' + PROJECT_NAME],
        #          hour=22, minute=0)
    ])
# yapf: enable


register(sys.modules[__name__])