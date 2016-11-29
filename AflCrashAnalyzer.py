#!/usr/bin/env python2.7
'''
    AFL crash analyzer, crash triage for the American Fuzzy Lop fuzzer
    Copyright (C) 2015  floyd

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

Created on Apr 13, 2015
@author: floyd, http://floyd.ch, @floyd_ch
'''

from modules.FileDuplicateFinder import FileDuplicateFinder
from modules.SignalFinder import SignalFinder
from modules.OutputFinder import OutputFinder
from modules.InputMinimizer import InputMinimizer
from modules.FeelingLuckyExploiter import FeelingLuckyExploiter
from modules.ExploitableGdbPlugin import ExploitableGdbPlugin
from utilities.Logger import Logger
import os
import glob

def analyze_output_and_exploitability(config, signal_finder, message_prefix=""):
    for signal, signal_folder in signal_finder.get_folder_paths_for_signals_if_exist(config):
        skip = False
        for cat in ExploitableGdbPlugin.get_classifications():
            if os.path.exists(os.path.join(signal_folder, cat)):
                Logger.warning("Seems like there are already exploitability analysis results, skipping. If you want to rerun: rm -r %s" % os.path.join(signal_folder, cat))
                skip = True
        if not skip:
            Logger.info(message_prefix, "Discover stdout, stderr, gdb and ASAN output (signal %s)" % signal)
            wildcard_for_run_output_files = os.path.join(signal_folder, "*" + config.run_extension)
            if glob.glob(wildcard_for_run_output_files):
                Logger.warning("Seems like there are already results from running the binaries, skipping. If you want to rerun: rm", wildcard_for_run_output_files)
            else:
                of = OutputFinder(config, signal_folder)
                of.do_sane_output_runs()
            
            Logger.info(message_prefix, "Analyzing exploitability (signal %s)" % signal)
            egp = ExploitableGdbPlugin(config, signal_folder)
            egp.divide_by_exploitability()

def main():
    #Read the README before you start.
    
    Logger.info("Setting up configuration")

    gdb_script_64bit = r"""printf "[+] Disabling verbose and complaints\n"
set verbose off
set complaints 0
printf "[+] Backtrace:\n"
bt
printf "[+] info reg:\n"
info reg
printf "[+] exploitable:\n"
exploitable
printf "[+] disassemble $rip, $rip+16:\n"
disassemble $rip, $rip+16
printf "[+] list\n"
list
"""
    gdb_script_32bit = r"""printf "[+] Disabling verbose and complaints\n"
set verbose off
set complaints 0
printf "[+] Backtrace:\n"
bt
printf "[+] info reg:\n"
info reg
printf "[+] exploitable:\n"
exploitable
printf "[+] disassemble $eip, $eip+16:\n"
disassemble $eip, $eip+16
printf "[+] list\n"
list
"""

    #TODO: Make sure gdb script doesn't abort on error
    #ignoring errors in gdb scripts: http://stackoverflow.com/questions/17923865/gdb-stops-in-a-command-file-if-there-is-an-error-how-to-continue-despite-the-er
    gdb_script_32bit_noerror = r"""python
def my_ignore_errors(arg):
  try:
    gdb.execute("print \"" + "Executing command: " + arg + "\"")
    gdb.execute (arg)
  except:
    gdb.execute("print \"" + "ERROR: " + arg + "\"")

my_ignore_errors("p p")
my_ignore_errors("p p->v1")
gdb.execute("quit")
    """

    where_this_python_script_lives = os.path.dirname(os.path.realpath(__file__))
    
    gdb_command = "/usr/bin/gdb"
    #gdb_command_osx = "/opt/local/bin/gdb-apple"
    
    #TODO: For some reason the ASAN environment variables are not correctly set when given to the subprocess module... so let's just set it in parent process already:
    os.environ['ASAN_SYMBOLIZER_PATH'] = "/usr/bin/llvm-symbolizer-3.4"
    os.environ['ASAN_OPTIONS'] = "symbolize=1:redzone=512:quarantine_size=512Mb:exitcode=1:abort_on_error=1"
    env={"ASAN_SYMBOLIZER_PATH": "/usr/bin/llvm-symbolizer-3.4", "ASAN_OPTIONS": "symbolize=1:redzone=512:quarantine_size=512Mb:exitcode=1:abort_on_error=1"}
    
    ###
    #This import decides which testcase/binary we want to run!
    ###
    from testcases.ffmpeg.Config import create_config
    #from testcases.ffmpeg.Config import create_config
    #see CrashAnalysisConfig for more options that get passed on by create_config
    chosen_config = create_config(where_this_python_script_lives, env=env, gdb_script=gdb_script_32bit, gdb_binary=gdb_command)
    chosen_config.sanity_check()
    
    #
    Logger.info("Input crashes directory operations")
    #
    
    Logger.info("Removing README.txt files")
    fdf = FileDuplicateFinder(chosen_config, chosen_config.original_crashes_directory)
    fdf.remove_readmes()
    
    Logger.info("Removing duplicates from original crashes folder (same file size + MD5)")
    fdf.delete_duplicates_recursively()
    
    Logger.info("Renaming files from original crashes folder so that the filename is a unique identifier. This allows us to copy all crash files into one directory (eg. for tmin output) if necessary, without name collisions")
    fdf.rename_same_name_files()
    #OR:
    #Logger.info("Renaming all files to numeric values, as some programs prefer no special chars in filenames and might require a specific file extension")
    #fdf.rename_all_files(".png")
    
    if chosen_config.ignore_signals == range(0,129):
        Logger.info("Finding interesting signals (using default config - all crashes)")
    else:
        Logger.info("Finding interesting signals (using target-specific config)")

    sf_all_crashes = SignalFinder(chosen_config)
    if os.path.exists(chosen_config.default_signal_directory):
        Logger.warning("Seems like all crashes were already categorized by signal, skipping. If you want to rerun: rm -r", chosen_config.default_signal_directory)
    else:
        Logger.debug("Dividing files to output folder according to their signal")
        sf_all_crashes.divide_by_signal()
    
    analyze_output_and_exploitability(chosen_config, sf_all_crashes, message_prefix="Interesting signals /")
        
    Logger.info("Interesting signals / Minimizing input (afl-tmin)")
    if os.path.exists(chosen_config.default_minimized_crashes_directory):
        Logger.warning("Seems like crashes were already minimized, skipping. If you want to rerun: rm -r", chosen_config.default_minimized_crashes_directory)
    else:
        for signal, signal_folder in sf_all_crashes.get_folder_paths_for_signals_if_exist(chosen_config):
            Logger.debug("Minimizing inputs resulting in signal %i" % signal)
            im = InputMinimizer(chosen_config, signal_folder)
            im.minimize_testcases()
        
        Logger.info("Interesting signals / Minimized inputs / Deduplication")
        fdf_minimized = FileDuplicateFinder(chosen_config, chosen_config.default_minimized_crashes_directory)
        fdf_minimized.delete_duplicates_recursively()
        
    #
    Logger.info("Interesting signals / Minimized inputs / Finding interesting signals")
    #
    sf_minimized_crashes = SignalFinder(chosen_config, chosen_config.default_minimized_crashes_directory, os.path.join(chosen_config.output_dir, "minimized-per-signal"))
    if os.path.exists(sf_minimized_crashes.output_dir):
        Logger.warning("Seems like minimized crashes were already categorized by signal, skipping. If you want to rerun: rm -r", sf_minimized_crashes.output_dir)
    else:
        os.mkdir(sf_minimized_crashes.output_dir)
        Logger.info("Dividing files to output folder according to their signal")
        sf_minimized_crashes.divide_by_signal(0)
    
    
    analyze_output_and_exploitability(chosen_config, sf_minimized_crashes, message_prefix="Interesting signals / Minimized inputs /")
    
#TODO:
#- Make (some) modules work as standalone applications with command line parsing
#- The FeelingLuckyExplotier thing. Need to get a small test sample where I know it should work.
#     # If you are in the mood to waste a little CPU time, run this
#     Logger.info("Found interesting_signals (interesting interesting_signals) / Minimized inputs (interested interesting_signals) / Feeling lucky auto exploitation")
#     #
#     fle = FeelingLuckyExploiter(chosen_config, sf_minimized_crashes.output_dir)
#     #os.mkdir(fle.output_dir)
#     fle.run_forest_run()


    cleanup(chosen_config)

def cleanup(config):
    for path, _, files in os.walk(config.tmp_dir):
        for filename in files:
            os.remove(os.path.join(path, filename))

if __name__ == "__main__":
    main()




