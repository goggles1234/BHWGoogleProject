# Author: Chad Lester
# Copyright (C) 2002 - 2006, Google Inc.
# Design and style contributions by:
#   Amit Patel, Bogdan Cocosel, Daniel Dulitz, Eric Tiedemann,
#   Eric Veach, Laurence Gonsalves, Matthew Springer
# Code reorganized a bit by Craig Silverstein

"""
This module is used to define and parse command line flags.

This module defines a *distributed* flag-definition policy: rather
than an application having to define all flags in or near main(), each
python module defines flags that are useful to it.  When one python
module imports another, it gains access to the other's flags.  (This
is implemented by having all modules share a common, global registry
object containing all the flag information.)

Flags are defined through the use of one of the DEFINE_xxx functions.
The specific function used determines how the flag is parsed, checked,
and optionally type-converted, when it's seen on the command line.


IMPLEMENTATION: DEFINE_* creates a 'Flag' object and registers it with
a 'FlagValues' object (typically the global FlagValues FLAGS, defined
here).  The 'FlagValues' object can scan the command line arguments
and pass flag arguments to the corresponding 'Flag' objects for
value-checking and type conversion.  The converted flag values are
available as members of the 'FlagValues' object.

Code can access the flag through a FlagValues object, for instancee
flags.FLAGS.myflag.  Typically, the __main__ module passes the command
line arguments to flags.FLAGS for parsing.

At bottom, this module calls getopt(), so getopt functionality is
supported, including short- and long-style flags, and the use of -- to
terminate flags.

Methods defined by the flag module will throw 'FlagsError' exceptions.
The exception argument will be a human-readable string.


FLAG TYPES:  This is a list of the DEFINE_*'s that you can do.  All
flags take a name, default value, help-string, and optional 'short'
name (one-letter name).  Some flags have other arguments, which are
described with the flag.

DEFINE_string: takes any input, and interprets it as a string.

DEFINE_boolean: typically does not take an argument: say --myflag to
                set FLAGS.myflag to true, or --nomyflag to set
                FLAGS.myflag to false.  Alternately, you can say
                   --myflag=true  or --myflag=t or --myflag=1  or
                   --myflag=false or --myflag=f or --myflag=0

DEFINE_float: takes an input and interprets it as a floating point
              number.  Takes optional args lower_bound and
              upper_bound; if the number specified on the command line
              is out of range, it will raise a FlagError.

DEFINE_integer: takes an input and interprets it as an integer.  Takes
                optional args lower_bound and upper_bound as for floats.

DEFINE_enum: takes a list of strings which represents legal values.  If
             the command-line value is not in this list, raise a flag
             error.  Otherwise, assign to FLAGS.flag as a string.

DEFINE_list: Takes a comma-separated list of strings on the commandline.
             Stores them in a python list object.

DEFINE_spaceseplist: Takes a space-separated list of strings on the
                     commandline.  Stores them in a python list object.

DEFINE_multistring: The same as DEFINE_string, except the flag can be
                    specified more than once on the commandline.  The
                    result is a python list object (list of strings),
                    even if the flag is only on the command line once.

DEFINE_multi_int: The same as DEFINE_integer, except the flag can be
                  specified more than once on the commandline.  The
                  result is a python list object (list of ints),
                  even if the flag is only on the command line once.


SPECIAL FLAGS: There are a few flags that have special meaning:
   --help          prints a list of all the flags in a human-readable fashion
   --flagfile=foo  read flags from foo.
   --undefok=f1,f2 ignore unrecognized option errors for f1,f2
   --              as in getopt(), terminates flag-processing

Note on --flagfile:

Flags may be loaded from text files in addition to being specified on
the commandline.

Any flags you don't feel like typing, throw them in a file, one flag
per line, for instance:
   --myflag=myvalue
   --nomyboolean_flag
You then specify your file with the special flag
'--flagfile=somefile'.  You CAN recursively nest flagfile= tokens OR
use multiple files on the command line.  Lines beginning with a single
hash '#' or a double slash '//' are comments in your flagfile.

Any flagfile=<file> will be interpreted as having a relative path from
the current working directory rather than from the place the file was
included from:
   myPythonScript.py --flagfile=config/somefile.cfg

If somefile.cfg includes further --flagfile= directives, these will be
referenced relative to the original CWD, not from the directory the
including flagfile was found in!

The caveat applies to people who are including a series of nested
files in a different dir than they are executing out of.  Relative
path names are always from CWD, not from the directory of the parent
include flagfile. We do now support '~' expanded directory names.

Absolute path names ALWAYS work!


EXAMPLE USAGE:

  from google3.pyglib import app
  from google3.pyglib import flags

  FLAGS = flags.FLAGS

  # Flag names are globally defined!  So in general, we need to be
  # careful to pick names that are unlikely to be used by other libraries.
  # If there is a conflict, we'll get an error at import time.
  flags.DEFINE_string('name', 'Mr. President', 'your name')
  flags.DEFINE_integer('age', None, 'your age in years', lower_bound=0)
  flags.DEFINE_boolean('debug', 0, 'produces debugging output')
  flags.DEFINE_enum('gender', 'male', ['male', 'female'], 'your gender')

  def main(argv):
    if FLAGS.debug and len(argv) > 1:
      print 'unparsed arguments:', argv[1:]
    print 'Happy Birthday', FLAGS.name
    if FLAGS.age is not None:
      print 'You are a %s, who is %d years old' % (FLAGS.gender, FLAGS.age)

  if __name__ == '__main__':
    app.run()
"""

import getopt
import os
import re
import sys

# Are we running at least python 2.2?
try:
  if tuple(sys.version_info[:3]) < (2,2,0):
    raise NotImplementedError("requires python 2.2.0 or later")
except AttributeError:   # a very old python, that lacks sys.version_info
  raise NotImplementedError("requires python 2.2.0 or later")

# If we're not running at least python 2.2.1, define True, False, and bool.
# Thanks, Guido, for the code.
try:
  True, False, bool
except NameError:
  False = 0
  True = 1
  def bool(x):
    if x:
      return True
    else:
      return False

# Are we running under pychecker?
_RUNNING_PYCHECKER = 'pychecker.python' in sys.modules


def _GetCallingModule():
  """
  Get the name of the module that's calling into this module; e.g.,
  the module calling a DEFINE_foo... function.
  """
  # Walk down the stack to find the first globals dict that's not ours.
  for depth in range(1, sys.getrecursionlimit()):
    if not sys._getframe(depth).f_globals is globals():
      return __GetModuleName(sys._getframe(depth).f_globals)
  raise AssertionError, "No module was found"


# module exceptions:
class FlagsError(Exception):
  """The base class for all flags errors"""

class DuplicateFlag(FlagsError):
  """Raised if there is a flag naming conflict"""

# A DuplicateFlagError conveys more information than
# a DuplicateFlag. Since there are external modules
# that create DuplicateFlags, the interface to
# DuplicateFlag shouldn't change.
class DuplicateFlagError(DuplicateFlag):
  def __init__(self, flagname, flag_values):
    self.flagname = flagname
    message = "The flag '%s' is defined twice." % self.flagname
    flags_by_module = flag_values.__dict__['__flags_by_module']
    for module in flags_by_module:
      for flag in flags_by_module[module]:
        if flag.name == flagname:
          message = message + " First from " + module + ","
          break
    message = message + " Second from " + _GetCallingModule()
    Exception.__init__(self, message)

class IllegalFlagValue(FlagsError): "The flag command line argument is illegal"

class UnrecognizedFlag(FlagsError):
  """Raised if a flag is unrecognized"""

# An UnrecognizedFlagError conveys more information than
# an UnrecognizedFlag. Since there are external modules
# that create DuplicateFlags, the interface to
# DuplicateFlag shouldn't change.
class UnrecognizedFlagError(UnrecognizedFlag):
  def __init__(self, flagname):
    self.flagname = flagname
    Exception.__init__(self, "Unknown command line flag '%s'" % flagname)

# Global variable used by expvar
_exported_flags = {}
_help_width = 80  # width of help output


def GetHelpWidth():
  """
  Length of help to be used in TextWrap
  """
  global _help_width
  return _help_width


def CutCommonSpacePrefix(text):
  """
  Cut out a common space prefix. If the first line does not start with a space
  it is left as is and only in the remaining lines a common space prefix is
  being searched for. That means the first line will stay untouched. This is
  especially useful to turn doc strings into help texts. This is because some
  people prefer to have the doc comment start already after the apostrophy and
  then align the following lines while others have the apostrophies on a
  seperately line. The function also drops trailing empty lines and ignores
  empty lines following the initial content line while calculating the initial
  common whitespace.

  Args:
    text:  text to work on

  Returns:
    the resulting text
  """
  text_lines = text.splitlines()
  # Drop trailing empty lines
  while text_lines and not text_lines[-1]:
    text_lines = text_lines[:-1]
  if text_lines:
    # We got some content, is the first line starting with a space?
    if text_lines[0] and text_lines[0][0].isspace():
      text_first_line = []
    else:
      text_first_line = [text_lines.pop(0)]
    # Calculate length of common leading whitesppace (only over content lines)
    common_prefix = os.path.commonprefix([line for line in text_lines if line])
    space_prefix_len = len(common_prefix) - len(common_prefix.lstrip())
    # If we have a common space prefix, drop it from all lines
    if space_prefix_len:
      for index in xrange(len(text_lines)):
        if text_lines[index]:
          text_lines[index] = text_lines[index][space_prefix_len:]
    return '\n'.join(text_first_line + text_lines)
  return ''


def TextWrap(text, length=None, indent='', firstline_indent=None, tabs='    '):
  """
  Wrap a given text to a maximum line length and return it.
  We turn lines that only contain whitespace into empty lines.
  We keep new lines.
  We also keep tabs (e.g. we do not treat tabs as spaces).

  Args:
    text:             text to wrap
    length:           maximum length of a line, includes indentation
                      if this is None then use GetHelpWidth()
    indent:           indent for all but first line
    firstline_indent: indent for first line, if None then fall back to indent
    tabs:             replacement for tabs

  Returns:
    wrapped text

  Raises:
    CommandsError: if indent not shorter than length
    CommandsError: if firstline_indent not shorter than length
  """
  # Get defaults where callee used None
  if length is None:
    length = GetHelpWidth()
  if indent is None:
    indent = ''
  if len(indent) >= length:
    raise CommandsError('Indent must be shorter than length')
  # In line we will be holding the current line which is to be started with
  # indent (or firstline_indent if available) and then appended with words.
  if firstline_indent is None:
    firstline_indent = ''
    line = indent
  else:
    line = firstline_indent
    if len(firstline_indent) >= length:
      raise CommandsError('First iline indent must be shorter than length')

  # If the callee does not care about tabs we simply convert them to spaces
  # If callee wanted tabs to be single space then we do that already here.
  if not tabs or tabs == ' ':
    text = text.replace('\t', ' ')
  else:
    tabs_are_whitespace = not tabs.strip()

  line_regex = re.compile('([ ]*)(\t*)([^ \t]+)', re.MULTILINE)

  # Split the text into lines and the lines with the regex above. The resulting
  # lines are collected in result[]. For each split we get the spaces, the tabs
  # and the next non white space (e.g. next word).
  result = []
  for text_line in text.splitlines():
    # Store result length so we can find out whether processing the next line
    # gave any new content
    old_result_len = len(result)
    # Process next line with line_regex. For optimization we do an rstrip().
    # - process tabs (changes either line or word, see below)
    # - process word (first try to squeeze on line, then wrap or force wrap)
    # Spaces found on the line are ignored, they get added while wrapping as
    # needed.
    for spaces, current_tabs, word in line_regex.findall(text_line.rstrip()):
      # If tabs weren't converted to spaces, handle them now
      if current_tabs:
        # If the last thing we added was a space anyway then drop it. But
        # let's not get rid of the indentation.
        if (((result and line != indent) or
            (not result and line != firstline_indent)) and line[-1] == ' '):
          line = line[:-1]
        # Add the tabs, if that means adding whitespace, just add it at the
        # line, the rstrip() code while shorten the line down if necessary
        if tabs_are_whitespace:
          line += tabs * len(current_tabs)
        else:
          # if not all tab replacement is whitespace we prepend it to the word
          word = tabs * len(current_tabs) + word
      # Handle the case where word cannot be squeezed onto current last line
      if len(line) + len(word) > length and len(indent) + len(word) <= length:
        result.append(line.rstrip())
        line = indent + word
        word = ''
        # No space left on line or can we append a space?
        if len(line) + 1 >= length:
          result.append(line.rstrip())
          line = indent
        else:
          line += ' '
      # Add word and shorten it up to allowed line length. Restart next line
      # with indent and repeat, or add a space if we're done (word finished)
      # This deals with words that caanot fit on one line (e.g. indent + word
      # longer than allowed line length).
      while len(line) + len(word) >= length:
        line += word
        result.append(line[:length])
        word = line[length:]
        line = indent
      # Default case, simply append the word and a space
      if word:
        line += word + ' '
    # End of input line. If we have content we finish the line. If the
    # current line is just the indent but we had content in during this
    # original line then we need to add an emoty line.
    if (result and line != indent) or (not result and line != firstline_indent):
      result.append(line.rstrip())
    elif len(result) == old_result_len:
      result.append('')
    line = indent

  return '\n'.join(result)


def DocToHelp(doc):
  """
  Takes a __doc__ string and reformats it as help.
  """
  # Get rid of starting and ending white space. Using lstrip() or even strip()
  # could drop more than maximum of first line and right space of last line.
  doc = doc.strip()

  # Get rid of all empty lines
  whitespace_only_line = re.compile('^[ \t]+$', re.M)
  doc = whitespace_only_line.sub('', doc)

  # Cut out common space at line beginnings
  doc = CutCommonSpacePrefix(doc)

  # Just like this module's comment, comments tend to be aligned somehow.
  # In other words they all start with the same amount of white space
  # 1) keep double new lines
  # 2) keep ws after new lines if not empty line
  # 3) all other new lines shall be changed to a space
  # Solution: Match new lines between non white space and replace with space.
  doc = re.sub('(?<=\S)\n(?=\S)', ' ', doc, re.M)

  return doc


def __GetModuleName(globals_dict):
  """Given a globals dict, find the module in which it's defined."""
  for name, module in sys.modules.iteritems():
    if getattr(module, '__dict__', None) is globals_dict:
      if name == '__main__':
        return sys.argv[0]
      return name
  raise AssertionError, "No module was found"

def _GetMainModule():
  """Get the module name from which execution started."""
  for depth in range(1, sys.getrecursionlimit()):
    try:
      globals_of_main = sys._getframe(depth).f_globals
    except ValueError:
      return __GetModuleName(globals_of_main)
  raise AssertionError, "No module was found"


class FlagValues:
  """
  Used as a registry for 'Flag' objects.

  A 'FlagValues' can then scan command line arguments, passing flag
  arguments through to the 'Flag' objects that it owns.  It also
  provides easy access to the flag values.  Typically only one
  'FlagValues' object is needed by an application:  flags.FLAGS

  This class is heavily overloaded:

  'Flag' objects are registered via __setitem__:
       FLAGS['longname'] = x   # register a new flag

  The .value member of the registered 'Flag' objects can be accessed as
  members of this 'FlagValues' object, through __getattr__.  Both the
  long and short name of the original 'Flag' objects can be used to
  access its value:
       FLAGS.longname          # parsed flag value
       FLAGS.x                 # parsed flag value (short name)

  Command line arguments are scanned and passed to the registered 'Flag'
  objects through the __call__ method.  Unparsed arguments, including
  argv[0] (e.g. the program name) are returned.
       argv = FLAGS(sys.argv)  # scan command line arguments

  The original registered Flag objects can be retrieved through the use
  of the dictionary-like operator, __getitem__:
       x = FLAGS['longname']   # access the registered Flag object

  The str() operator of a 'FlagValues' object provides help for all of
  the registered 'Flag' objects.
  """

  def __init__(self):
    # Since everything in this class is so heavily overloaded,
    # the only way of defining and using fields is to access __dict__
    # directly.
    self.__dict__['__flags'] = {}
    self.__dict__['__flags_by_module'] = {} # A dict module -> list of flag

  def FlagDict(self):
    return self.__dict__['__flags']

  def _RegisterFlagByModule(self, module_name, flag):
    """We keep track of which flag is defined by which module so that
       we can later sort the flags by module.
    """
    flags_by_module = self.__dict__['__flags_by_module']
    flags_by_module.setdefault(module_name, []).append(flag)

  def AppendFlagValues(self, flag_values):
    """Append flags registered in another FlagValues instance.

    Args:
      flag_values: registry to copy from
    """
    for flag_name, flag in flag_values.FlagDict().iteritems():
      # Flags with shortnames will appear here twice (once with under
      # its normal name, and again with its short name).  To prevent
      # problems (DuplicateFlagError) that occur when doubly
      # registering flags, we perform a check to make sure that the
      # entry we're looking at is for its normal name.
      if flag_name == flag.name:
        self[flag_name] = flag

  def __setitem__(self, name, flag):
    """
    Register a new flag variable.
    """
    fl = self.FlagDict()
    if not isinstance(flag, Flag):
      raise IllegalFlagValue, flag
    if not isinstance(name, type("")):
      raise FlagsError, "Flag name must be a string"
    if len(name) == 0:
      raise FlagsError, "Flag name cannot be empty"
    # If running under pychecker, duplicate keys are likely to be defined.
    # Disable check for duplicate keys when pycheck'ing.
    if (fl.has_key(name) and not flag.allow_override and
        not fl[name].allow_override and not _RUNNING_PYCHECKER):
      raise DuplicateFlagError(name, self)
    short_name = flag.short_name
    if short_name is not None:
      if (fl.has_key(short_name) and not flag.allow_override and
          not fl[short_name].allow_override and not _RUNNING_PYCHECKER):
        raise DuplicateFlagError(short_name, self)
      fl[short_name] = flag
    fl[name] = flag
    global _exported_flags
    _exported_flags[name] = flag

  def __getitem__(self, name):
    """
    Retrieve the flag object.
    """
    return self.FlagDict()[name]

  def __getattr__(self, name):
    """
    Retrieve the .value member of a flag object.
    """
    fl = self.FlagDict()
    if not fl.has_key(name):
      raise AttributeError, name
    return fl[name].value

  def __setattr__(self, name, value):
    """
    Set the .value member of a flag object.
    """
    fl = self.FlagDict()
    fl[name].value = value
    return value

  def __delattr__(self, name):
    """
    Delete a previously-defined flag from a flag object.
    """
    fl = self.FlagDict()
    if not fl.has_key(name):
      raise AttributeError, name
    del fl[name]

  def SetDefault(self, name, value):
    """
    Change the default value of the named flag object.
    """
    fl = self.FlagDict()
    if not fl.has_key(name):
      raise AttributeError, name
    fl[name].SetDefault(value)

  def __contains__(self, name):
    """
    Return True if name is a value (flag) in the dict.
    """
    return name in self.FlagDict()

  has_key = __contains__  # a synonym for __contains__()

  def __iter__(self):
    return self.FlagDict().iterkeys()

  def __call__(self, argv):
    """
    Searches argv for flag arguments, parses them and then sets the flag
    values as attributes of this FlagValues object.  All unparsed
    arguments are returned.  Flags are parsed using the GNU Program
    Argument Syntax Conventions, using getopt:

    http://www.gnu.org/software/libc/manual/html_mono/libc.html#Getopt

    Args:
       argv: argument list. Can be of any type that may be converted to a list.

    Returns:
       The list of arguments not parsed as options, including argv[0]

    Raises:
       FlagsError: on any parsing error
    """
    # Support any sequence type that can be converted to a list
    argv = list(argv)

    shortopts = ""
    longopts = []

    fl = self.FlagDict()

    # This pre parses the argv list for --flagfile=<> options.
    argv = self.ReadFlagsFromFiles(argv)

    # Correct the argv to support the google style of passing boolean
    # parameters.  Boolean parameters may be passed by using --mybool,
    # --nomybool, --mybool=(true|false|1|0).  getopt does not support
    # having options that may or may not have a parameter.  We replace
    # instances of the short form --mybool and --nomybool with their
    # full forms: --mybool=(true|false).
    original_argv = list(argv)  # list() makes a copy
    shortest_matches = None
    for name, flag in fl.items():
      if not flag.boolean:
        continue
      if shortest_matches is None:
        # Determine the smallest allowable prefix for all flag names
        shortest_matches = self.ShortestUniquePrefixes(fl)
      no_name = 'no' + name
      prefix = shortest_matches[name]
      no_prefix = shortest_matches[no_name]

      # Replace all occurences of this boolean with extended forms
      for arg_idx in range(1, len(argv)):
        arg = argv[arg_idx]
        if arg.find('=') >= 0: continue
        if arg.startswith('--'+prefix) and ('--'+name).startswith(arg):
          argv[arg_idx] = ('--%s=true' % name)
        elif arg.startswith('--'+no_prefix) and ('--'+no_name).startswith(arg):
          argv[arg_idx] = ('--%s=false' % name)

    # Loop over all of the flags, building up the lists of short options and
    # long options that will be passed to getopt.  Short options are
    # specified as a string of letters, each letter followed by a colon if it
    # takes an argument.  Long options are stored in an array of strings.
    # Each string ends with an '=' if it takes an argument.
    for name, flag in fl.items():
      longopts.append(name + "=")
      if len(name) == 1:  # one-letter option: allow short flag type also
        shortopts += name
        if not flag.boolean:
          shortopts += ":"

    longopts.append('undefok=')
    undefok_flags = []

    # In case --undefok is specified, loop to pick up unrecognized
    # options one by one.
    unrecognized_opts = []
    args = argv[1:]
    while True:
      try:
        optlist, unparsed_args = getopt.getopt(args, shortopts, longopts)
        break
      except getopt.GetoptError, e:
        if not e.opt or e.opt in fl:
          # Not an unrecognized option, reraise the exception as a FlagsError
          raise FlagsError(e)
        # Handle an unrecognized option.
        unrecognized_opts.append(e.opt)
        # Remove offender from args and try again
        for arg_index in range(len(args)):
          if ((args[arg_index] == '--' + e.opt) or
              (args[arg_index] == '-' + e.opt) or
              args[arg_index].startswith('--' + e.opt + '=')):
            args = args[0:arg_index] + args[arg_index+1:]
            break
        else:
          # We should have found the option, so we don't expect to get
          # here.  We could assert, but raising the original exception
          # might work better.
          raise FlagsError(e)

    for name, arg in optlist:
      if name == '--undefok':
        undefok_flags.extend(arg.split(','))
        continue
      if name.startswith('--'):
        # long option
        name = name[2:]
        short_option = 0
      else:
        # short option
        name = name[1:]
        short_option = 1
      if fl.has_key(name):
        flag = fl[name]
        if flag.boolean and short_option: arg = 1
        flag.Parse(arg)

    # If there were unrecognized options, raise an exception unless
    # the options were named via --undefok.
    for opt in unrecognized_opts:
      if opt not in undefok_flags:
        raise UnrecognizedFlagError(opt)

    if unparsed_args:
      # unparsed_args becomes the first non-flag detected by getopt to
      # the end of argv.  Because argv may have been modified above,
      # return original_argv for this region.
      return argv[:1] + original_argv[-len(unparsed_args):]
    else:
      return argv[:1]

  def Reset(self):
    """
    Reset the values to the point before FLAGS(argv) was called.
    """
    for f in self.FlagDict().values():
      f.Unparse()

  def RegisteredFlags(self):
    """
    Return a list of all registered flags.
    """
    return self.FlagDict().keys()

  def FlagValuesDict(self):
    """
    Return a dictionary with flag names as keys and flag values as values.
    """
    flag_values = {}

    for flag_name in self.RegisteredFlags():
      flag = self.FlagDict()[flag_name]
      flag_values[flag_name] = flag.value

    return flag_values

  def __str__(self):
    """
    Generate a help string for all known flags.
    """
    return self.GetHelp()

  def GetHelp(self, prefix=""):
    """
    Generate a help string for all known flags.
    """
    helplist = []

    flags_by_module = self.__dict__['__flags_by_module']
    if flags_by_module:

      modules = flags_by_module.keys()
      modules.sort()

      # Print the help for the main module first, if possible.
      main_module = _GetMainModule()
      if main_module in modules:
        modules.remove(main_module)
        modules = [ main_module ] + modules

      for module in modules:
        self.__RenderOurModuleFlags(module, helplist)

      self.__RenderModuleFlags('google3.pyglib.flags',
                               _SPECIAL_FLAGS.FlagDict().values(),
                               helplist)

    else:
      # Just print one long list of flags.
      self.__RenderFlagList(
          self.FlagDict().values() + _SPECIAL_FLAGS.FlagDict().values(),
          helplist, prefix)

    return '\n'.join(helplist)

  def __RenderModuleFlags(self, module, flags, output_lines, prefix=""):
    """
    Generate a help string for a given module.
    """
    output_lines.append('\n%s%s:' % (prefix, module))
    self.__RenderFlagList(flags, output_lines, prefix + "  ")

  def __RenderOurModuleFlags(self, module, output_lines, prefix=""):
    """
    Generate a help string for a given module.
    """
    flags_by_module = self.__dict__['__flags_by_module']
    if module in flags_by_module:
      self.__RenderModuleFlags(module, flags_by_module[module],
                               output_lines, prefix)

  def MainModuleHelp(self):
    """
    Generate a help string for all known flags of the main module.
    """
    helplist = []
    self.__RenderOurModuleFlags(_GetMainModule(), helplist)
    return '\n'.join(helplist)

  def __RenderFlagList(self, flaglist, output_lines, prefix="  "):
    fl = self.FlagDict()
    special_fl = _SPECIAL_FLAGS.FlagDict()
    flaglist = [(flag.name, flag) for flag in flaglist]
    flaglist.sort()
    flagset = {}
    for (name, flag) in flaglist:
      # It's possible this flag got deleted or overridden since being
      # registered in the per-module flaglist.  Check now against the
      # canonical source of current flag information, the FlagDict.
      if fl.get(name, None) != flag and special_fl.get(name, None) != flag:
        # a different flag is using this name now
        continue
      # only print help once
      if flagset.has_key(flag): continue
      flagset[flag] = 1
      flaghelp = ""
      if flag.short_name: flaghelp += "-%s," % flag.short_name
      if flag.boolean:
        flaghelp += "--[no]%s" % flag.name + ":"
      else:
        flaghelp += "--%s" % flag.name + ":"
      flaghelp += "  "
      if flag.help:
        flaghelp += flag.help
      flaghelp = TextWrap(flaghelp, indent=prefix+"  ",
                          firstline_indent=prefix)
      if flag.default_as_str:
        flaghelp += "\n"
        flaghelp += TextWrap("(default: %s)" % flag.default_as_str,
                             indent=prefix+"  ")
      if flag.parser.syntactic_help:
        flaghelp += "\n"
        flaghelp += TextWrap("(%s)" % flag.parser.syntactic_help,
                             indent=prefix+"  ")
      output_lines.append(flaghelp)

  def get(self, name, default):
    """
    Retrieve the .value member of a flag object, or default if .value is None
    """

    value = self.__getattr__(name)
    if value is not None: # Can't do if not value, b/c value might be '0' or ""
      return value
    else:
      return default

  def ShortestUniquePrefixes(self, fl):
    """
    Returns a dictionary mapping flag names to their shortest unique prefix.
    """
    # Sort the list of flag names
    sorted_flags = []
    for name, flag in fl.items():
      sorted_flags.append(name)
      if flag.boolean:
        sorted_flags.append('no%s' % name)
    sorted_flags.sort()

    # For each name in the sorted list, determine the shortest unique prefix
    # by comparing itself to the next name and to the previous name (the latter
    # check uses cached info from the previous loop).
    shortest_matches = {}
    prev_idx = 0
    for flag_idx in range(len(sorted_flags)):
      curr = sorted_flags[flag_idx]
      if flag_idx == (len(sorted_flags) - 1):
        next = None
      else:
        next = sorted_flags[flag_idx+1]
        next_len = len(next)
      for curr_idx in range(len(curr)):
        if (next is None
            or curr_idx >= next_len
            or curr[curr_idx] != next[curr_idx]):
          # curr longer than next or no more chars in common
          shortest_matches[curr] = curr[:max(prev_idx, curr_idx) + 1]
          prev_idx = curr_idx
          break
      else:
        # curr shorter than (or equal to) next
        shortest_matches[curr] = curr
        prev_idx = curr_idx + 1 # next will need at least one more char
    return shortest_matches

  def __IsFlagFileDirective(self, flag_string):
    """ Detects the --flagfile= token.
    Takes a string which might contain a '--flagfile=<foo>' directive.
    Returns a Boolean.
    """
    if isinstance(flag_string, type("")):
      if flag_string.startswith('--flagfile='):
        return 1
      elif flag_string == '--flagfile':
        return 1
      elif flag_string.startswith('-flagfile='):
        return 1
      elif flag_string == '-flagfile':
        return 1
      else:
        return 0
    return 0

  def ExtractFilename(self, flagfile_str):
    """Function to remove the --flagfile= (or variant) and return just the
      filename part.  We can get strings that look like:
        --flagfile=foo, -flagfile=foo.
      The case of --flagfile foo and  -flagfile foo shouldn't be hitting this
      function, as they are dealt with in the level above this funciton.
    """
    if flagfile_str.startswith('--flagfile='):
      return os.path.expanduser((flagfile_str[(len('--flagfile=')):]).strip())
    elif flagfile_str.startswith('-flagfile='):
      return os.path.expanduser((flagfile_str[(len('-flagfile=')):]).strip())
    else:
      raise FlagsError('Hit illegal --flagfile type: %s' % flagfile_str)
      return ''


  def __GetFlagFileLines(self, filename, parsed_file_list):
    """Function to open a flag file, return its useful (!=comments,etc) lines.
    Takes:
        A filename to open and read
        A list of files we have already read THAT WILL BE CHANGED
    Returns:
        List of strings. See the note below.

    NOTE(springer): This function checks for a nested --flagfile=<foo>
    tag and handles the lower file recursively. It returns a list off
    all the lines that _could_ contain command flags.  This is
    EVERYTHING except whitespace lines and comments (lines starting
    with '#' or '//').
    """
    line_list = []  # All line from flagfile.
    flag_line_list = []  # Subset of lines w/o comments, blanks, flagfile= tags.
    try:
      file_obj = open(filename, 'r')
    except IOError, e_msg:
      print e_msg
      print 'ERROR:: Unable to open flagfile: %s' % (filename)
      return flag_line_list

    line_list = file_obj.readlines()
    file_obj.close()
    parsed_file_list.append(filename)

    # This is where we check each line in the file we just read.
    for line in line_list:
      if line.isspace():
        pass
      # Checks for comment (a line that starts with '#').
      elif (line.startswith('#') or line.startswith('//')):
        pass
      # Checks for a nested "--flagfile=<bar>" flag in the current file.
      # If we find one, recursively parse down into that file.
      elif self.__IsFlagFileDirective(line):
        sub_filename = self.ExtractFilename(line)
        # We do a little safety check for reparsing a file we've already done.
        if not sub_filename in parsed_file_list:
          included_flags = self.__GetFlagFileLines(sub_filename, parsed_file_list)
          flag_line_list.extend(included_flags)
        else: # Case of hitting a circularly included file.
          print >>sys.stderr, ('Warning: Hit circular flagfile dependency: %s'
                                                                 % sub_filename)
      else:
        # Any line that's not a comment or a nested flagfile should
        # get copied into 2nd position, this leaves earlier arguements
        # further back in the list, which makes them have higher priority.
        flag_line_list.append(line.strip())
    return flag_line_list

  def ReadFlagsFromFiles(self, argv):
    """Process command line args, but also allow args to be read from file
    Usage:
      Takes: a list of strings, usually sys.argv, which may contain one or more
            flagfile directives of the form --flagfile="./filename"
      References: Global pyglib.flags.FLAG class instance
      Returns: a new list which has the original list combined with what we
                 read from any flagfile(s).

      This function should be called  before the normal FLAGS(argv) call.
      This function simply scans the input list for a flag that looks like:
         --flagfile=<somefile>
      Then it opens <somefile>, reads all valid key and value pairs and inserts
      them into the input list between the first item of the list and any
      subsequent items in the list.
      Note that your application's flags are still defined the usual way using
      pyglib.flags DEFINE_flag() type functions.

      Notes (assuming we're getting a commandline of some sort as our input):
      --> Any flags on the command line we were passed in _should_ always take
              precedence!!!
      --> a further "--flagfile=<otherfile.cfg>" CAN be nested in a flagfile.
              It will be processed after the parent flag file is done.
      --> For duplicate flags, first one we hit should "win".
      --> In a flagfile, a line beginning with # or // is a comment
      --> Entirely blank lines _should_ be ignored
    """
    parsed_file_list = []
    rest_of_args = argv
    new_argv = []
    while rest_of_args:
      current_arg = rest_of_args[0]
      rest_of_args = rest_of_args[1:]
      if self.__IsFlagFileDirective(current_arg):
        # This handles the case of -(-)flagfile foo.  Inthis case the next arg
        # really is part of this one.
        if current_arg == '--flagfile' or current_arg =='-flagfile':
          if not rest_of_args:
            raise IllegalFlagValue, '--flagfile with no argument'
          flag_filename = os.path.expanduser(rest_of_args[0])
          rest_of_args = rest_of_args[1:]
        else:
          # This handles the case of (-)-flagfile=foo.
          flag_filename = self.ExtractFilename(current_arg)
        new_argv = (new_argv[:1] +
                self.__GetFlagFileLines(flag_filename, parsed_file_list) +
                new_argv[1:])
      else:
        new_argv.append(current_arg)

    return new_argv

  def FlagsIntoString(self):
    """
    Retrieve a string version of all the flags with assignments stored
    in this FlagValues object.  Should mirror the behavior of the c++
    version of FlagsIntoString.  Each flag assignment is seperated by
    a newline.
    """
    s = ''
    for flag in self.FlagDict().values():
      if flag.value is not None:
        s += flag.Serialize() + '\n'
    return s

  def AppendFlagsIntoFile(self, filename):
    """
    Appends all flags found in this FlagInfo object to the file
    specified.  Output will be in the format of a flagfile.  This
    should mirror the behavior of the c++ version of
    AppendFlagsIntoFile.
    """
    out_file = open(filename, 'a')
    out_file.write(self.FlagsIntoString())
    out_file.close()
# end of FlagValues definition

# The global FlagValues instance
FLAGS = FlagValues()


class Flag:
  """
  'Flag' objects define the following fields:
    .name  - the name for this flag
    .default - the default value for this flag
    .default_as_str - default value as repr'd string, e.g., "'true'" (or None)
    .value  - the most recent parsed value of this flag; set by Parse()
    .help  - a help string or None if no help is available
    .short_name  - the single letter alias for this flag (or None)
    .boolean  - if 'true', this flag does not accept arguments
    .present  - true if this flag was parsed from command line flags.
    .parser  - an ArgumentParser object
    .serializer - an ArgumentSerializer object
    .allow_override - the flag may be redefined without raising an error

  The only public method of a 'Flag' object is Parse(), but it is
  typically only called by a 'FlagValues' object.  The Parse() method is
  a thin wrapper around the 'ArgumentParser' Parse() method.  The parsed
  value is saved in .value, and the .present member is updated.  If this
  flag was already present, a FlagsError is raised.

  Parse() is also called during __init__ to parse the default value and
  initialize the .value member.  This enables other python modules to
  safely use flags even if the __main__ module neglects to parse the
  command line arguments.  The .present member is cleared after __init__
  parsing.  If the default value is set to None, then the __init__
  parsing step is skipped and the .value member is initialized to None.

  Note: The default value is also presented to the user in the help
  string, so it is important that it be a legal value for this flag.
  """
  def __init__(self, parser, serializer, name, default, help_string,
               short_name=None, boolean=0, allow_override=0):
    self.name = name

    if not help_string:
      help_string = '(no help available)'

    self.help = help_string
    self.short_name = short_name
    self.boolean = boolean
    self.present = 0
    self.parser = parser
    self.serializer = serializer
    self.allow_override = allow_override
    self.value = None

    self.SetDefault(default)

  def __GetParsedValueAsString(self, value):
    if value is None:
      return None
    if self.serializer:
      return repr(self.serializer.Serialize(value))
    if self.boolean:
      if value:
        return repr('true')
      else:
        return repr('false')
    return repr(str(value))

  def Parse(self, argument):
    try:
      self.value = self.parser.Parse(argument)
    except ValueError, e:  # recast ValueError as IllegalFlagValue
      raise IllegalFlagValue, ("flag --%s: " % self.name) + str(e)
    self.present += 1

  def Unparse(self):
    if self.default is None:
      self.value = None
    else:
      self.Parse(self.default)
    self.present = 0

  def Serialize(self):
    if self.value is None:
      return ''
    if self.boolean:
      if self.value:
        return "--%s" % self.name
      else:
        return "--no%s" % self.name
    else:
      if not self.serializer:
        raise FlagsError, "Serializer not present for flag %s" % self.name
      return "--%s=%s" % (self.name, self.serializer.Serialize(self.value))

  def SetDefault(self, value):
    """
    Change the default value, and current value, of this flag object
    """
    # We can't allow a None override because it may end up not being
    # passed to C++ code when we're overriding C++ flags.  So we
    # cowardly bail out until someone fixes the semantics of trying to
    # pass None to a C++ flag.  See swig_flags.Init() for details on
    # this behavior.
    if value is None and self.allow_override:
      raise DuplicateFlag, self.name

    self.default = value
    self.Unparse()
    self.default_as_str = self.__GetParsedValueAsString(self.value)
# End of Flag definition

class ArgumentParser:
  """
  This is a base class used to parse and convert arguments.

  The Parse() method checks to make sure that the string argument is a
  legal value and convert it to a native type.  If the value cannot be
  converted, it should throw a 'ValueError' exception with a human
  readable explanation of why the value is illegal.

  Subclasses should also define a syntactic_help string which may be
  presented to the user to describe the form of the legal values.
  """
  syntactic_help = ""
  def Parse(self, argument):
    """
    The default implementation of Parse() accepts any value of argument,
    simply returning it unmodified.
    """
    return argument

class ArgumentSerializer:
  """
  This is the base class for generating string representations of a
  flag value
  """
  def Serialize(self, value):
    return str(value)

class ListSerializer(ArgumentSerializer):
  def __init__(self, list_sep):
    self.list_sep = list_sep

  def Serialize(self, value):
    return self.list_sep.join([str(x) for x in value])


# The DEFINE functions are explained in the module doc string.

def DEFINE(parser, name, default, help, flag_values=FLAGS, serializer=None,
           **args):
  """
  This creates a generic 'Flag' object that parses its arguments with a
  'Parser' and registers it with a 'FlagValues' object.

  Developers who need to create their own 'Parser' classes should call
  this module function. to register their flags.  For example:

  DEFINE(DatabaseSpec(), "dbspec", "mysql:db0:readonly:hr",
         "The primary database")
  """
  DEFINE_flag(Flag(parser, serializer, name, default, help, **args),
              flag_values)

def DEFINE_flag(flag, flag_values=FLAGS):
  """
  This registers a 'Flag' object with a 'FlagValues' object.  By
  default, the global FLAGS 'FlagValue' object is used.

  Typical users will use one of the more specialized DEFINE_xxx
  functions, such as DEFINE_string or DEFINE_integer.  But developers
  who need to create Flag objects themselves should use this function to
  register their flags.
  """
  # copying the reference to flag_values prevents pychecker warnings
  fv = flag_values
  fv[flag.name] = flag

  if flag_values == FLAGS:
    # We are using the global flags dictionary, so we'll want to sort the
    # usage output by calling module in FlagValues.__str__ (FLAGS is an
    # instance of FlagValues). This requires us to keep track
    # of which module is creating the flags.

    # Tell FLAGS who's defining flag.
    FLAGS._RegisterFlagByModule(_GetCallingModule(), flag)


###############################
#################  STRING FLAGS
###############################

def DEFINE_string(name, default, help, flag_values=FLAGS, **args):
  """
  This registers a flag whose value can be any string.
  """
  parser = ArgumentParser()
  serializer = ArgumentSerializer()
  DEFINE(parser, name, default, help, flag_values, serializer, **args)


###############################
################  BOOLEAN FLAGS
###############################

class BooleanParser(ArgumentParser):
  """
  A boolean value
  """

  def Convert(self, argument):
    """
    convert the argument to a boolean; raise ValueError on errors
    """
    if type(argument) == str:
      if argument.lower() in ['true', 't', '1']:
        return True
      elif argument.lower() in ['false', 'f', '0']:
        return False

    bool_argument = bool(argument)
    if argument == bool_argument:
      # The argument is a valid boolean (True, False, 0, or 1), and not just
      # something that always converts to bool (list, string, int, etc.).
      return bool_argument

    raise ValueError('Non-boolean argument to boolean flag', argument)

  def Parse(self, argument):
    val = self.Convert(argument)
    return val

class BooleanFlag(Flag):
  """
  A basic boolean flag.  Boolean flags do not take any arguments, and
  their value is either True (1) or False (0).  The false value is
  specified on the command line by prepending the word 'no' to either
  the long or short flag name.

  For example, if a Boolean flag was created whose long name was 'update'
  and whose short name was 'x', then this flag could be explicitly unset
  through either --noupdate or --nox.
  """
  def __init__(self, name, default, help, short_name=None, **args):
    p = BooleanParser()
    Flag.__init__(self, p, None, name, default, help, short_name, 1, **args)
    if not self.help: self.help = "a boolean value"

def DEFINE_boolean(name, default, help, flag_values=FLAGS, **args):
  """
  This registers a boolean flag - one that does not take an argument.
  If a user wants to specify a false value explicitly, the long option
  beginning with 'no' must be used: i.e. --noflag

  This flag will have a value of None, True or False.  None is possible if
  default=None and the user does not specify the flag on the command
  line.
  """
  DEFINE_flag(BooleanFlag(name, default, help, **args), flag_values)


###############################
##################  FLOAT FLAGS
###############################

class FloatParser(ArgumentParser):
  """
  A floating point value; optionally bounded to a given upper and lower
  bound.
  """
  number_article = "a"
  number_name = "number"
  syntactic_help = " ".join((number_article, number_name))

  def __init__(self, lower_bound=None, upper_bound=None):
    self.lower_bound = lower_bound
    self.upper_bound = upper_bound
    sh = self.syntactic_help
    if lower_bound != None and upper_bound != None:
      sh = ("%s in the range [%s, %s]" % (sh, lower_bound, upper_bound))
    elif lower_bound == 1:
      sh = "a positive %s" % self.number_name
    elif upper_bound == -1:
      sh = "a negative %s" % self.number_name
    elif lower_bound == 0:
      sh = "a non-negative %s" % self.number_name
    elif upper_bound != None:
      sh = "%s <= %s" % (self.number_name, upper_bound)
    elif lower_bound != None:
      sh = "%s >= %s" % (self.number_name, lower_bound)
    self.syntactic_help = sh

  def Convert(self, argument):
    """
    convert the argument to a float; raise ValueError on errors
    """
    return float(argument)

  def Parse(self, argument):
    val = self.Convert(argument)
    if ((self.lower_bound != None and val < self.lower_bound) or
        (self.upper_bound != None and val > self.upper_bound)):
      raise ValueError, "%s is not %s" % (val, self.syntactic_help)
    return val

def DEFINE_float(name, default, help, lower_bound=None, upper_bound=None,
                 flag_values = FLAGS, **args):
  """
  This registers a flag whose value must be a float.  If lower_bound,
  or upper_bound are set, then this flag must be within the given range.
  """
  parser = FloatParser(lower_bound, upper_bound)
  serializer = ArgumentSerializer()
  DEFINE(parser, name, default, help, flag_values, serializer, **args)


###############################
################  INTEGER FLAGS
###############################

class IntegerParser(FloatParser):
  """
  An integer value; optionally bounded to a given upper or lower bound.
  """
  number_article = "an"
  number_name = "integer"
  syntactic_help = " ".join((number_article, number_name))
  def Convert(self, argument):
    __pychecker__ = 'no-returnvalues'
    if type(argument) == str:
      base = 10
      if len(argument) > 2 and argument[0] == "0" and argument[1] == "x":
        base=16
      try:
        return int(argument, base)
      # ValueError is thrown when argument is a string, and overflows an int.
      except ValueError:
        return long(argument, base)
    else:
      try:
        return int(argument)
      # OverflowError is thrown when argument is numeric, and overflows an int.
      except OverflowError:
        return long(argument)

def DEFINE_integer(name, default, help, lower_bound=None, upper_bound=None,
                   flag_values = FLAGS, **args):
  """
  This registers a flag whose value must be an integer.  If lower_bound,
  or upper_bound are set, then this flag must be within the given range.
  """
  parser = IntegerParser(lower_bound, upper_bound)
  serializer = ArgumentSerializer()
  DEFINE(parser, name, default, help, flag_values, serializer, **args)


###############################
###################  ENUM FLAGS
###############################

class EnumParser(ArgumentParser):
  """
  A string enum value
  """

  def __init__(self, enum_values=None):
    self.enum_values = enum_values

  def Parse(self, argument):
    """
    If enum_values is not specified, any string is allowed
    """
    if self.enum_values and argument not in self.enum_values:
      raise ValueError, ("value should be one of <%s>"
                         % "|".join(self.enum_values))
    return argument

class EnumFlag(Flag):
  """
  A basic enum flag. The flag's value can be any string from the list
  of enum_values.
  """
  def __init__(self, name, default, help, enum_values=[],
               short_name=None, **args):
    p = EnumParser(enum_values)
    g = ArgumentSerializer()
    Flag.__init__(self, p, g, name, default, help, short_name, **args)
    if not self.help: self.help = "an enum string"
    self.help = "<%s>: %s" % ("|".join(enum_values), self.help)

def DEFINE_enum(name, default, enum_values, help, flag_values=FLAGS,
                **args):
  """
  This registers a flag whose value can be a string from a set of
  specified values.
  """
  DEFINE_flag(EnumFlag(name, default, help, enum_values, ** args),
              flag_values)


###############################
###################  LIST FLAGS
###############################

class BaseListParser(ArgumentParser):
  """
  A base class for a string list parser.
  To extend, inherit from this class, and call

  BaseListParser.__init__(self, token, name)

  where token is a character used to tokenize, and
  name is a description of the separator
  """

  def __init__(self, token=None, name=None):
    assert name
    self._token = token
    self._name = name
    self.syntactic_help = "a %s separated list" % self._name

  def Parse(self, argument):
    if argument == '':
      return []
    else:
      return [s.strip() for s in argument.split(self._token)]


class ListParser(BaseListParser):
  """
  A string list parser (comma-separated)
  """

  def __init__(self):
    BaseListParser.__init__(self, ',', 'comma')

class WhitespaceSeparatedListParser(BaseListParser):
  """
  A string list parser (whitespace-separated)
  """

  def __init__(self):
    BaseListParser.__init__(self, None, 'whitespace')


def DEFINE_list(name, default, help, flag_values=FLAGS, **args):
  """
  This registers a flag whose value is a list of strings, separated by commas
  """
  parser = ListParser()
  serializer = ListSerializer(',')
  DEFINE(parser, name, default, help, flag_values, serializer, **args)

def DEFINE_spaceseplist(name, default, help, flag_values=FLAGS, **args):
  """
  This registers a flag whose value is a list of strings, separated by any
  whitespace
  """
  parser = WhitespaceSeparatedListParser()
  serializer = ListSerializer(' ')
  DEFINE(parser, name, default, help, flag_values, serializer, **args)


###############################
##################  MULTI FLAGS
###############################

class MultiFlag(Flag):
  """
  MultiFlag is a specialized subclass of Flag that accumulates
  multiple values in a list when a command-line option appears
  multiple times.

  See the __doc__ for Flag for most behavior of this class.  Only
  differences in behavior are described here:
   * the default value may be a single value -OR- a list of values
   * the value of the flag is always a list, even if the option was only
     supplied once, and even if the default value is a single value
  """
  def __init__(self, *args, **kwargs):
    Flag.__init__(self, *args, **kwargs)

    self.help = (self.help +
                 ';\n    repeat this option to specify a list of values')

  def Parse(self, arguments):
    """Parse one or more arguments with the installed parser.

    Arguments:
      arguments:  a single argument or a list of arguments (typically a list
        of default values); single arguments will be converted internally into
        a list containing one item
    """
    if not isinstance(arguments, list):
      # Default value may be a list of values.  Most other arguments will not
      # be, so convert them into a single-item list to make processing simpler
      # below.
      arguments = [ arguments ]

    if self.present:
      # keep a backup reference to list of previously supplied option values
      values = self.value
    else:
      # "erase" the defaults with an empty list
      values = []

    for item in arguments:
      # have Flag superclass parse argument, overwriting self.value reference
      Flag.Parse(self, item)  # also increments self.present
      values.append(self.value)

    # put list of option values back in member variable
    self.value = values

  def Serialize(self):
    if not self.serializer:
      raise FlagsError, "Serializer not present for flag %s" % self.name
    if self.value is None:
      return ''

    s = ''

    multi_value = self.value

    for self.value in multi_value:
      if s: s += ' '
      s += Flag.Serialize(self)

    self.value = multi_value

    return s


def DEFINE_multi(parser, serializer, name, default, help, flag_values=FLAGS,
                 **args):
  """
  This creates a generic 'MultiFlag' object that parses its arguments with a
  'Parser' and registers it with a 'FlagValues' object.

  Developers who need to create their own 'Parser' classes for options which
  can appear multiple times can call this module function to register their
  flags.
  """
  DEFINE_flag(MultiFlag(parser, serializer, name, default, help, **args), flag_values)

def DEFINE_multistring(name, default, help, flag_values=FLAGS, **args):
  """
  This registers a flag whose value can be a list of any strings.  Use the flag
  on the command line multiple times to place multiple string values into the
  list.  The 'default' may be a single string (which will be converted into a
  single-element list) or a list of strings.
  """
  parser = ArgumentParser()
  serializer = ArgumentSerializer()
  DEFINE_multi(parser, serializer, name, default, help, flag_values, **args)

def DEFINE_multi_int(name, default, help, lower_bound=None, upper_bound=None,
                     flag_values=FLAGS, **args):
  """
  This registers a flag whose value can be a list of any integers.  Use the
  flag on the command line multiple times to place multiple integer values
  into the list.  The 'default' may be a single integer (which will be
  converted into a single-element list) or a list of integers.
  """
  parser = IntegerParser(lower_bound, upper_bound)
  serializer = ArgumentSerializer()
  DEFINE_multi(parser, serializer, name, default, help, flag_values, **args)

# Define special flags here so that help may be generated for them.
_SPECIAL_FLAGS = FlagValues()

DEFINE_string(
    'flagfile', "",
    "Insert flag definitions from the given file into the command line.",
    _SPECIAL_FLAGS)

DEFINE_string(
    'undefok', "",
    "comma-separated list of flag names that it is okay to specify "
    "on the command line even if the program does not define a flag "
    "with that name.  IMPORTANT: flags in this list that have "
    "arguments MUST use the --flag=value format.", _SPECIAL_FLAGS)
