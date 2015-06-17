#!/usr/bin/env python
#
# Copyright 2015 Janos Czentye <czentye@tmit.bme.hu>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Top starter script of ESCAPEv2 for convenient purposes
"""
import argparse
import os

parser = argparse.ArgumentParser(
  description="ESCAPE: Extensible Service ChAin Prototyping Environment using "
              "Mininet, Click, NETCONF and POX")
parser.add_argument("-v", "--version", action="version", version="2.0.0")
escape = parser.add_argument_group("ESCAPE arguments")
escape.add_argument("-d", "--debug", action="store_true", default=False,
                    help="run the ESCAPE in debug mode")
escape.add_argument("-f", "--full", action="store_true", default=False,
                    help="run the infrastructure layer also")
escape.add_argument("-i", "--interactive", action="store_true", default=False,
                    help="run an interactive shell for observing internal "
                         "states")
args = parser.parse_args()
cmd = "pox/pox.py unify"
if args.full:
  cmd = "sudo %s --full" % cmd
if args.debug:
  # Nothing to do
  pass
else:
  cmd = "%s --debug=False" % cmd
if args.interactive:
  cmd = "%s py --completion" % cmd
print "Starting ESCAPEv2..."
os.system(cmd)
