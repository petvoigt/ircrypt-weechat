# -*- coding: utf-8 -*-
#
# Copyright 2013
#    Lars Kiesow   <lkiesow@uos.de>
#    Sven Haardiek <sven@haardiek.de>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHORS OR CONTRIBUTORS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
# THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation
# are those of the authors and should not be interpreted as representing
# official policies, either expressed or implied, of everyone working on
# this project.
#
#
# Suggestions, Bugs, ...?
# https://github.com/IRCrypt/ircrypt-weechat
#


SCRIPT_NAME    = 'IRCrypt'
SCRIPT_AUTHOR  = 'Sven Haardiek <sven@haardiek.de>, Lars Kiesow <lkiesow@uos.de>'
SCRIPT_VERSION = '0.1'
SCRIPT_LICENSE = 'FreeBSD License'
SCRIPT_DESC    = 'IRCrypt: Encryption layer for IRC'

import weechat, string, os, subprocess, base64
import time


ircrypt_msg_buffer = {}
ircrypt_config_file = None
ircrypt_config_section = {}
ircrypt_config_option = {}
ircrypt_keys = {}


class MessageParts:
	modified = None
	last_id  = None
	message  = ''

	def update(self, id, msg):
		# Check if id is correct. If not, throw away old parts:
		if last_id and last_id != id+1:
			self.message = ''
		# Check if the are old message parts which belong due to their old age 
		# (> 5min) probably not to this message:
		if time.time() - self.modified > 300:
			self.message = ''
		self.last_id = id
		self.message = msg + self.message
		self.modified = time.time()



def decrypt(data, msgtype, servername, args):
	'''Hook for incomming PRVMSG commands.
	This method will parse the input, check if it is an encrypted message and if
	it is, decrypt it.

	:param data:
	:param msgtype:
	:param servername: IRC server the message comes from.
	:param args: IRC command line-
	'''
	global ircrypt_msg_buffer, ircrypt_config_option, ircrypt_keys

	info = weechat.info_get_hashtable("irc_message_parse", { "message": args })
	key = ircrypt_keys.get('%s/%s' % (servername, info['channel']))

	# Stop if there is no key for this conversation
	if not key:
		return args

	pre, message    = string.split(args, '>CRY-', 1)
	number, message = string.split(message, ' ', 1 )

	# Get key forthe message buffer
	buf_key = '%s.%s.%s' % (servername, dict['channel'], dict['nick'])

	# Decrypt only if we got last part of the message
	# otherwise put the message into a globa buffer and quit
	if int(number) != 0:
		if not buf_key in ircrypt_msg_buffer:
			ircrypt_msg_buffer[buf_key] = MessageParts()
		ircrypt_msg_buffer[buf_key].update(int(number), message)
		return ''

	# Get whole message
	try:
		message = message + ircrypt_msg_buffer[buf_key].message
	except KeyError:
		pass

	# Decrypt
	p = subprocess.Popen(['gpg', '--batch',  '--no-tty', '--quiet', 
		'--passphrase-fd', '-', '-d'], 
		stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	p.stdin.write('passwort1\n')
	p.stdin.write(base64.b64decode(message))
	p.stdin.close()
	decrypted = p.stdout.read()
	p.stdout.close()

	# Get and print GPG errors/warnings
	err = p.stderr.read()
	p.stderr.close()
	if err:
		buf = weechat.buffer_search('irc', '%s.#IRCrypt' % servername)
		weechat.prnt(buf, 'GPG reported error:\n%s' % err)

	# Remove old messages from buffer
	try:
		del ircrypt_msg_buffer[buf_key]
	except KeyError:
		pass
	return '%s%s%s' % (ircrypt_config_option.get('encrypted') or '', pre, decrypted)



def encrypt(data, msgtype, servername, args):
	'''Hook for outgoing PRVMSG commands.
	This method will encrypt outgoing messages and if necessary (if they grow to
	large) split them into multiple parts.

	:param data:
	:param msgtype:
	:param servername: IRC server the message comes from.
	:param args: IRC command line-
	'''
	global ircrypt_keys
	info = weechat.info_get_hashtable("irc_message_parse", { "message": args })
	key = ircrypt_keys.get('%s/%s' % (servername, info['channel']))

	# Stop if there is no key for this conversation
	if not key:
		return args

	pre, message = string.split(args, ':', 1)
	p = subprocess.Popen(['gpg', '--batch',  '--no-tty', '--quiet', 
		'--symmetric', '--cipher-algo', 'TWOFISH', '--passphrase-fd', '-'], 
		stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	p.stdin.write('%s\n' % key)
	p.stdin.write(message)
	p.stdin.close()
	encrypted = base64.b64encode(p.stdout.read())
	p.stdout.close()
	# Get and print GPG errors/warnings
	err = p.stderr.read()
	p.stderr.close()
	if err:
		buf = weechat.buffer_search('irc', '%s.#IRCrypt' % servername)
		weechat.prnt(buf, 'GPG reported error:\n%s' % err)

	output = '%s:>CRY-0 %s' % (pre, encrypted)
	# Check if encrypted message is to long.
	# If that is the case, send multiple messages.
	if len(output) > 400:
		output = '%s:>CRY-1 %s\r\n%s' % (pre, output[400:], output[:400])
	return output


def ircrypt_config_init():
	''' Initialize config file: create sections and options in memory. '''
	global ircrypt_config_file, ircrypt_config_section, ircrypt_config_option
	ircrypt_config_file = weechat.config_new('ircrypt', 'ircrypt_config_reload_cb', '')
	if not ircrypt_config_file:
		return

	# marker
	ircrypt_config_section['marker'] = weechat.config_new_section(
			ircrypt_config_file, 'marker', 0, 0, '', '', '', '', '', '', '', '', '', '')
	if not ircrypt_config_section['marker']:
		weechat.config_free(ircrypt_config_file)
		return
	ircrypt_config_option['encrypted'] = weechat.config_new_option(
			ircrypt_config_file, ircrypt_config_section['marker'],
			'encrypted', 'string', 'Marker for encrypted messages', '', 0, 0,
			'', '', 0, '', '', '', '', '', '')
	ircrypt_config_option['unencrypted'] = weechat.config_new_option(
			ircrypt_config_file, ircrypt_config_section['marker'], 'unencrypted',
			'string', 'Marker for unencrypted messages received in an encrypted channel', 
			'', 0, 0, '', '', 0, '', '', '', '', '', '')

	# keys
	ircrypt_config_section['keys'] = weechat.config_new_section(
			ircrypt_config_file, 'keys', 0, 0, 'ircrypt_config_keys_read_cb', '',
			'ircrypt_config_keys_write_cb', '', '',
		'', '', '', '', '')
	if not ircrypt_config_section['keys']:
		weechat.config_free(ircrypt_config_file)


def ircrypt_config_reload_cb(data, config_file):
	''' Reload config file. '''
	return weechat.WEECHAT_CONFIG_READ_OK


def ircrypt_config_read():
	''' Read ircrypt config file (ircrypt.conf). '''
	global ircrypt_config_file
	return weechat.config_read(ircrypt_config_file)


def ircrypt_config_write():
	''' Write ircrypt config file (ircrypt.conf). '''
	global ircrypt_config_file
	return weechat.config_write(ircrypt_config_file)


def ircrypt_config_keys_read_cb(data, config_file, section_name, option_name,
		value):
	global ircrypt_keys

	if not weechat.config_new_option(config_file, section_name, option_name,
			'string', 'key', '', 0, 0, '', value, 0, '', '', '', '', '', ''):
		return weechat.WEECHAT_CONFIG_OPTION_SET_ERROR

	ircrypt_keys[option_name] = value
	return weechat.WEECHAT_CONFIG_OPTION_SET_OK_CHANGED


def ircrypt_config_keys_write_cb(data, config_file, section_name):
	global ircrypt_keys

	weechat.config_write_line(config_file, section_name, '')
	for target, key in sorted(ircrypt_keys.iteritems()):
		weechat.config_write_line(config_file, target, key)

	return weechat.WEECHAT_RC_OK


def ircrypt_command(data, buffer, args):
	'''Hook to handle the /ircrypt weechat command.
	'''
	global ircrypt_keys

	if args == '' or args == 'list':
		#ircrypt_list_keys(buffer)
		return weechat.WEECHAT_RC_OK

	argv = [a for a in args.split(' ') if a]
	weechat.prnt('', '>> %s' % argv)

	# Check if a server was set
	if (len(argv) > 2 and argv[1] == '-server'):
		server_name = argv[2]
		del argv[2]
		del argv[1]
		args = args.split(' ', 2)[-1]
	else:
		server_name = weechat.buffer_get_string(buffer, 'localvar_server')

	# We need at least one additional argument
	if len(argv) < 2:
		return weechat.WEECHAT_RC_ERROR

	target = '%s/%s' % (server_name, argv[1])

	# Set keys
	if argv[0] == 'set':
		if len(argv) != 3:
			return weechat.WEECHAT_RC_ERROR
		ircrypt_keys[target] = ' '.join(argv[2:])
		weechat.prnt(buffer, 'set key for %s' % target)
		return weechat.WEECHAT_RC_OK

	# Remove keys
	if argv[0] == 'remove':
		if len(argv) != 2:
			return weechat.WEECHAT_RC_ERROR
		if target not in ircrypt_keys:
			return weechat.WEECHAT_RC_ERROR

		del ircrypt_keys[target]
		weechat.prnt(buffer, 'removed key for %s' % target)
		return weechat.WEECHAT_RC_OK

	# Error if command was unknown
	return weechat.WEECHAT_RC_ERROR


# register plugin
if weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, SCRIPT_LICENSE,
		SCRIPT_DESC, 'ircrypt_unload_script', 'UTF-8'):
	# register the modifiers
	weechat.hook_modifier('irc_in_privmsg', 'decrypt', '')
	weechat.hook_modifier('irc_out_privmsg', 'encrypt', '')

	weechat.hook_command('ircrypt', 'Manage IRCrypt Keys',
			'[list] | set [-server <server>] <target> <key> '
			'| remove [-server <server>] <target>',
			'Add, change or remove key for target.\n'
			'Target can be a channel or a nick.\n\n'
			'Examples:\n'
			'Set the key for a channel: /ircrypt set -server freenet #blowfish key\n'
			'Remove the key:            /ircrypt remove #blowfish\n'
			'Set the key for a user :   /ircrypt set nick secret+key\n',
			'list || set %(irc_channel)|%(nicks)|-server %(irc_servers) %- '
			'|| remove %(irc_channel)|%(nicks)|-server %(irc_servers) %- ',
			'ircrypt_command', '')

	ircrypt_config_init()
	ircrypt_config_read()


def ircrypt_unload_script():
	ircrypt_config_write()
	return weechat.WEECHAT_RC_OK
