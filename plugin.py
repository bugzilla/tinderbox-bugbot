###
# Copyright (c) 2007, Max Kanat-Alexander
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
import supybot.world as world
import supybot.plugins as plugins
import supybot.ircmsgs as ircmsgs
import supybot.schedule as schedule
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks

import re
import socket
import urllib
import urllib2

# Build|Bugzilla|checksetup landfill|busted|1186119893
BUILD_RE = re.compile('Build\|(?P<tree>.+)\|(?P<build>.+)\|(?P<state>.+)\|(?P<time>.+)$')
# State|Firefox|SeaMonkey|open
STATE_RE = re.compile('State\|(?P<tree>.+)\|.+\|(?P<state>.+)$')

# The maximum number of times we will try to get a URL if it times out.
FETCH_MAX = 3

class StateNotBuildException(Exception):
    pass

class TinderboxParseError(Exception):
    pass

class TinderboxBuild:
    """Represents a single build in a Tinderbox tree."""
    
    def __init__(self, string):
        match = BUILD_RE.search(string)
        if not match:
            raise TinderboxParseError, "Couldn't parse %s" % string
        self.fields = match.groupdict()
        
    def name(self):
        return self.fields['build']
    def status(self):
        return self.fields['state']
    def tree(self):
        return self.fields['tree']


class Tinderbox(callbacks.Plugin):
    """Interacts with Tinderbox 1 installations."""
    threaded = True
    
    def __init__(self, irc):
        self.__parent = super(Tinderbox, self)
        self.__parent.__init__(irc)
        
        self.current_trees = {};
        for channel in irc.state.channels.keys():
            self.current_trees[channel] = \
                self._get_trees(self.registryValue('trees', channel))
        period = self.registryValue('pollTime')
        schedule.addPeriodicEvent(self._pollTrees, period, name=self.name(),
                                  now=False)

    def die(self): 
        self.__parent.die()
        schedule.removeEvent(self.name())
    
    def builds(self, irc, msg, args, tree):
        """<tree>
        Shows the state of builds in the specified tree."""
        
        channel = msg.args[0]
        tree = tree.strip()
        trees = self._get_trees([tree])
        
        for build in trees[tree].values():
            irc.reply("%s: %s" % (build.name(), build.status()))
    builds = wrap(builds, ['text'])

#    def poll(self, irc, msg, args):   
    def _pollTrees(self):
        for irc in world.ircs:
            for channel in irc.state.channels.keys():
                trees = self._get_trees(self.registryValue('trees', channel))
                current = {}
                
                if channel in self.current_trees:
                    current = self.current_trees[channel]
                
                # Check for new and changed builds.
                for tree in trees.keys():
                    if tree not in current: continue
                    
                    for build in trees[tree].keys():
                        # Check if this is a new build
                        if build not in current[tree]:
                            self._send(irc, channel,
                                "New build added to %s: %s (state: %s)." \
                                % (tree, build, trees[tree][build].status()))
                        else:
                            # Check if the status of the build has changed.
                            old_status = current[tree][build].status()
                            new_status = trees[tree][build].status();
                            if (old_status != new_status):
                                self._send(irc, channel,
                                    "%s: '%s' has changed state from %s to %s."\
                                    % (tree, build, old_status, new_status))
                
                # Check for dropped builds
                for tree in current.keys():
                    if tree not in trees: continue
                    
                    for build in current[tree].keys():
                        if build not in trees[tree]:
                            self._send(irc, channel,
                                "Build '%s' has dropped from the %s tinderbox."\
                                % (build, tree))
                        
                self.current_trees[channel] = trees

    def _send(self, irc, channel, line):
        msg = ircmsgs.privmsg(channel, line)
        irc.queueMsg(msg)
    
    def _get_trees(self, trees):
        # Eliminate empty strings that show up sometimes
        tree_names = [urllib.quote(t) for t in trees if t]
        if not tree_names: return {}
        
        url = "%sshowbuilds.cgi?quickparse=1&tree=%s" % \
              (self.registryValue('url'), ','.join(tree_names))
        self.log.debug('Getting trees from %s' % url)
        
        tree_data = self._getUrl(url)
        
        builds = []
        for line in tree_data.splitlines():
            if STATE_RE.search(line): continue
            builds.append(TinderboxBuild(line))
        
        tree_dict = {}
        for build in builds:
            if build.tree() not in tree_dict:
                tree_dict[build.tree()] = {}
            tree_dict[build.tree()][build.name()] = build;
            
        return tree_dict

    # Connecting to Tinderbox times out a lot, so we want something that
    # deals better with timeouts than utils.web.getUrl.
    def _getUrl(self, url):
        fetch_count = 0
        fetched = False
        while (fetched == False):
            try:
                fd = urllib2.urlopen(url)
                fetched = True
            except socket.timeout, e:
                fetch_count = fetch_count + 1
                if fetch_count == FETCH_MAX: raise
            except:
                raise
        
        text = fd.read()
        fd.close()
        return text
            

Class = Tinderbox


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
