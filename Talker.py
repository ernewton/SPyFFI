'''Every thing inherits from Talker, so we can print text to the terminal in a relatively standard way.'''
import textwrap

class Talker(object):
    '''Objects the inherit from Talker have "mute" and "pithy" attributes, a report('uh-oh!') method that prints when unmuted, and a speak('yo!') method that prints only when unmuted and unpithy.'''
    def __init__(self, mute=False, pithy=False, line=100):
        self.mute = False
        self.pithy = False
        self.line = line

    def speak(self, string, level=0):
        '''If verbose=True and terse=False, this will print to terminal. Otherwise, it won't.'''
        if self.pithy == False:
            self.report(string, level)

    def report(self, string, level=0):
        '''If verbose=True, this will print to terminal. Otherwise, it won't.'''
        if self.mute == False:
            self.prefix = '{spacing}[{name}] '.format(name = self.__class__.__name__.lower(), spacing = ' '*level)
            self.prefix = "{0:>16}".format(self.prefix)
            equalspaces = ' '*len(self.prefix)
            print textwrap.fill(self.prefix + string.replace('\n', '\n' + equalspaces), self.line, subsequent_indent=equalspaces + '... ')
