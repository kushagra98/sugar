# Copyright (C) 2006-2007, Red Hat, Inc.
# Copyright (C) 2009 Simon Schampijer
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import logging
import subprocess
import errno
import traceback
import sys

import dbus
import gtk

from sugar._sugarext import KeyGrabber

from jarabe.model import screen
from jarabe.model import sound
from jarabe.model import shell
from jarabe.model import session
from jarabe.view.tabbinghandler import TabbingHandler
from jarabe.model.shell import ShellModel
from jarabe import config
from jarabe.journal import journalactivity

_BRIGHTNESS_STEP = 2
_VOLUME_STEP = sound.VOLUME_STEP
_BRIGHTNESS_MAX = 15
_VOLUME_MAX = 100
_TABBING_MODIFIER = gtk.gdk.MOD1_MASK

_actions_table = {
    'F1'                   : 'zoom_mesh',
    'F2'                   : 'zoom_group',
    'F3'                   : 'zoom_home',
    'F4'                   : 'zoom_activity',
    'F9'                   : 'brightness_down',
    'F10'                  : 'brightness_up',
    '<alt>F9'              : 'brightness_min',
    '<alt>F10'             : 'brightness_max',
    'XF86AudioMute'        : 'volume_mute',
    'F11'                  : 'volume_down',
    'XF86AudioLowerVolume' : 'volume_down',
    'F12'                  : 'volume_up',
    'XF86AudioRaiseVolume' : 'volume_up',
    '<alt>F11'             : 'volume_min',
    '<alt>F12'             : 'volume_max',
    '0x93'                 : 'frame',
    '0xEB'                 : 'rotate',
    '<alt>Tab'             : 'next_window',
    '<alt><shift>Tab'      : 'previous_window',
    '<alt>Escape'          : 'close_window',
    '0xDC'                 : 'open_search',
# the following are intended for emulator users
    '<alt><shift>f'        : 'frame',
    '<alt><shift>q'        : 'quit_emulator',
    '<alt><shift>o'        : 'open_search',
    '<alt><shift>r'        : 'rotate',
    '<alt><shift>s'        : 'say_text',
}

SPEECH_DBUS_SERVICE = 'org.laptop.Speech'
SPEECH_DBUS_PATH = '/org/laptop/Speech'
SPEECH_DBUS_INTERFACE = 'org.laptop.Speech'

class KeyHandler(object):
    def __init__(self, frame):
        self._frame = frame
        self._screen_rotation = 0
        self._key_pressed = None
        self._keycode_pressed = 0
        self._keystate_pressed = 0
        self._speech_proxy = None

        self._key_grabber = KeyGrabber()
        self._key_grabber.connect('key-pressed',
                                  self._key_pressed_cb)
        self._key_grabber.connect('key-released',
                                  self._key_released_cb)

        self._tabbing_handler = TabbingHandler(self._frame, _TABBING_MODIFIER)

        for f in os.listdir(os.path.join(config.ext_path, 'globalkey')):
            if f.endswith('.py') and not f.startswith('__'):
                module_name = f[:-3]
                try:
                    logging.debug('Loading module %r' % module_name)
                    module = __import__('globalkey.' + module_name, globals(),
                                        locals(), [module_name])
                    for key in module.BOUND_KEYS:
                        if key in _actions_table:
                            raise ValueError('Key %r is already bound' % key)
                        _actions_table[key] = module
                except:
                    logging.error('Exception while loading extension:\n' + \
                                  traceback.format_exc())

        self._key_grabber.grab_keys(_actions_table.keys())

    def _change_volume(self, step=None, value=None):
        if step is not None:
            volume = sound.get_volume() + step
        elif value is not None:
            volume = value

        volume = min(max(0, volume), _VOLUME_MAX)

        sound.set_volume(volume)
        sound.set_muted(volume == 0)

    def _change_brightness(self, step=None, value=None):
        if step is not None:
            level = screen.get_display_brightness() + step
        elif value is not None:
            level = value

        level = min(max(0, level), _BRIGHTNESS_MAX)

        screen.set_display_brightness(level)
        if level == 0:
            screen.set_display_mode(screen.B_AND_W_MODE)
        else:
            screen.set_display_mode(screen.COLOR_MODE)

    def _get_speech_proxy(self):
        if self._speech_proxy is None:
            bus = dbus.SessionBus()
            speech_obj = bus.get_object(SPEECH_DBUS_SERVICE, SPEECH_DBUS_PATH,
                                        follow_name_owner_changes=True)
            self._speech_proxy = dbus.Interface(speech_obj,
                                                SPEECH_DBUS_INTERFACE)
        return self._speech_proxy

    def _on_speech_err(self, ex):
        logging.error("An error occurred with the ESpeak service: %r" % (ex, ))

    def _primary_selection_cb(self, clipboard, text, user_data):
        logging.debug('KeyHandler._primary_selection_cb: %r' % text)
        if text:
            self._get_speech_proxy().SayText(text, reply_handler=lambda: None, \
                error_handler=self._on_speech_err)

    def handle_say_text(self):
        clipboard = gtk.clipboard_get(selection="PRIMARY")
        clipboard.request_text(self._primary_selection_cb)

    def handle_previous_window(self):
        self._tabbing_handler.previous_activity()

    def handle_next_window(self):
        self._tabbing_handler.next_activity()

    def handle_close_window(self):
        active_activity = shell.get_model().get_active_activity()
        if active_activity.is_journal():
            return

        active_activity.get_window().close()

    def handle_zoom_mesh(self):
        shell.get_model().zoom_level = ShellModel.ZOOM_MESH

    def handle_zoom_group(self):
        shell.get_model().zoom_level = ShellModel.ZOOM_GROUP

    def handle_zoom_home(self):
        shell.get_model().zoom_level = ShellModel.ZOOM_HOME

    def handle_zoom_activity(self):
        shell.get_model().zoom_level = ShellModel.ZOOM_ACTIVITY

    def handle_brightness_max(self):
        self._change_brightness(value=_BRIGHTNESS_MAX)

    def handle_brightness_min(self):
        self._change_brightness(value=0)

    def handle_volume_max(self):
        self._change_volume(value=_VOLUME_MAX)

    def handle_volume_min(self):
        self._change_volume(value=0)

    def handle_brightness_up(self):
        self._change_brightness(step=_BRIGHTNESS_STEP)

    def handle_brightness_down(self):
        self._change_brightness(step=-_BRIGHTNESS_STEP)

    def handle_volume_mute(self):
        self._change_volume(value=0)

    def handle_volume_up(self):
        self._change_volume(step=_VOLUME_STEP)

    def handle_volume_down(self):
        self._change_volume(step=-_VOLUME_STEP)

    def handle_frame(self):
        self._frame.notify_key_press()

    def handle_rotate(self):
        """
        Handles rotation of the display (using xrandr) and of the d-pad.

        Notes: default mappings for keypad on MP
        KP_Up 80
        KP_Right 85
        KP_Down 88
        KP_Left 83
        """

        states = [ 'normal', 'left', 'inverted', 'right']
        keycodes = (80, 85, 88, 83, 80, 85, 88, 83)
        keysyms = ("KP_Up", "KP_Right", "KP_Down", "KP_Left")

        self._screen_rotation -= 1
        self._screen_rotation %= 4

        actual_keycodes = keycodes[self._screen_rotation:self._screen_rotation 
                                   + 4]
        # code_pairs now contains a mapping of keycode -> keysym in the current
        # orientation
        code_pairs = zip(actual_keycodes, keysyms)

        # Using the mappings in code_pairs, we dynamically build up an xmodmap
        # command to rotate the dpad keys.
        argv = ['xmodmap']
        for arg in [('-e', 'keycode %i = %s' % p) for p in code_pairs]:
            argv.extend(arg)

        # If either the xmodmap or xrandr command fails, check_call will fail
        # with CalledProcessError, which we raise.
        try:
            subprocess.check_call(argv)
            subprocess.check_call(['xrandr', '-o', 
                                   states[self._screen_rotation]])
        except OSError, e:
            if e.errno != errno.EINTR:
                raise

    def handle_quit_emulator(self):
        session.get_session_manager().shutdown()

    def handle_open_search(self):
        journalactivity.get_journal().focus_search()

    def _key_pressed_cb(self, grabber, keycode, state):
        key = grabber.get_key(keycode, state)
        logging.debug('_key_pressed_cb: %i %i %s' % (keycode, state, key))
        if key:
            self._key_pressed = key
            self._keycode_pressed = keycode
            self._keystate_pressed = state

            action = _actions_table[key]
            if self._tabbing_handler.is_tabbing():
                # Only accept window tabbing events, everything else
                # cancels the tabbing operation.
                if not action in ["next_window", "previous_window"]:
                    self._tabbing_handler.stop()
                    return True

            if hasattr(action, 'handle_key_press'):
                action.handle_key_press(key)
            elif isinstance(action, basestring):
                method = getattr(self, 'handle_' + action)
                method()
            else:
                raise TypeError('Invalid action %r' % action)

            return True
        else:
            # If this is not a registered key, then cancel tabbing.
            if self._tabbing_handler.is_tabbing():
                if not grabber.is_modifier(keycode):
                    self._tabbing_handler.stop()
                return True

        return False

    def _key_released_cb(self, grabber, keycode, state):
        if self._tabbing_handler.is_tabbing():
            # We stop tabbing and switch to the new window as soon as the
            # modifier key is raised again.
            if grabber.is_modifier(keycode, mask=_TABBING_MODIFIER):
                self._tabbing_handler.stop()

            return True
        return False

_instance = None

def setup(frame):
    global _instance

    if _instance:
        del _instance

    _instance = KeyHandler(frame)

