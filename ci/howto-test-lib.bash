
# Simplistic test framework for Wildland HOWTO
# 
# Usage: source this file in the test script, like this:
#  . ci/howto-test-lib.bash
#
# Then, prepend each command to be tested with 'run' function, like this:
#   run wl user list
#
# If you want to compare the command output with an expected value, set 'expected' variable first, like this:
#   expected="Some output
#   second line of output"
#   run wl user dump test
#

set -eo pipefail

. /home/user/env/bin/activate
pip install --no-deps . plugins/*

export PATH=$PATH:$(dirname "$0")/..
alias tree='/usr/bin/tree -A'
export LC_CTYPE=C.UTF-8

test_script=${BASH_SOURCE[-1]}
all_steps=$(grep -c '^run ' "$test_script")
current_step=0

red=$(tput setaf 1 2>/dev/null ||:)
norm=$(tput sgr0 2>/dev/null ||:)
bold=$(tput bold 2>/dev/null ||:)

# run the command, collect its output and, if $expected is set, compare with
# $expected variable content; clear $expected afterwards, to avoid confusion
run() {
    ((++current_step))
    printf '%s(%02d/%02d)%s $ %s%s\n' "$red" $current_step $all_steps "$norm$bold" "$*" "$norm"
    if ! actual=$("$@"); then
        printf '%s\n%s-> FAILED%s\n' "$actual" "$red$bold" "$norm"
        exit 1
    fi
    if [ "${expected-x}" != x ]; then
        if ! diff -u <(printf '%s' "$expected") <(printf '%s' "$actual"); then
            printf '%s-> OUTPUT DOES NOT MATCH%s\n' "$red$bold" "$norm"
            exit 1
        fi
        unset expected
    fi
    printf '%s\n\n' "$actual"
}