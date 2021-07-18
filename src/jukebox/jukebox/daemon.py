#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import sys
import signal
import logging
import importlib
import zmq

import jukebox.alsaif
import jukebox.Volume
import jukebox.System
import jukebox.plugs as plugin
from player import PlayerMPD
from jukebox.rpc.server import RpcServer
from jukebox.NvManager import nv_manager
from components.rfid_reader.PhonieboxRfidReader import RFID_Reader
# from gpio_control import gpio_control

import jukebox.cfghandler

logger = logging.getLogger('jb.daemon')
cfg = jukebox.cfghandler.get_handler('jukebox')


class JukeBox:
    def __init__(self, configuration_file):
        self.nvm = nv_manager()
        self.configuration_file = configuration_file

        jukebox.cfghandler.load_yaml(cfg, self.configuration_file)

        logger.info("Starting the " + cfg.getn('system', 'box_name', default='Jukebox2') + " Daemon")
        logger.info("Starting the " + cfg['system'].get('box_name', default='Jukebox2') + " Daemon")

        # setup the signal listeners
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        self.objects = {}

    def signal_handler(self, esignal, frame):
        # catches signal and triggers the graceful exit
        logger.info("Caught signal {} ({}) \n {}".format(signal.Signals(esignal).name, esignal, frame))
        self.exit_gracefully()

    def exit_gracefully(self):
        # TODO: Iterate over objects and tell them to exit
        # TODO: stop all threads
        # TODO: This check what happens with Threads here ...

        plugin.call_ignore_errors('player', 'ctrl', 'stop')

        if 'shutdown_sound' in cfg['jingle']:
            shutdown_sound_thread = plugin.call_ignore_errors('jingle', 'play_shutdown', as_thread=True)
            plugin.call_ignore_errors('jingle', 'play_shutdown')
        else:
            logger.debug("No shutdown sound in config file")

        # save all nonvolatile data
        self.nvm.save_all()
        jukebox.cfghandler.write_yaml(cfg, self.configuration_file, only_if_changed=True)

        # wait for shutdown sound to complete
        # shutdown_sound_thread.join()
        logger.info("Exiting")

        # TODO: implement shutdown ()
        sys.exit(0)

    def run(self):
        # Load the plugins
        plugins_named = cfg.getn('modules', 'named', default={})
        plugins_other = cfg.getn('modules', 'others', default=[])
        plugin.load_all_named(plugins_named, prefix='components')
        plugin.load_all_unnamed(plugins_other, prefix='components')
        plugin.load_all_finalize()

        # Initial testing code:
        # print(f"Callables = {plugin._PLUGINS}")
        # print(f"{plugin.modules['volume'].factory.list()}")
        # print(f"Volume factory = {plugin.get('volume', 'factory').list()}")

        # Testcode for switching to another volume control service ...
        # plugin.modules['volume'].factory.set_active("alsa2")
        # print(f"Callables = {plugin.callables}")

        if 'startup_sound' in cfg['jingle']:
            plugin.call_ignore_errors('jingle', 'play_startup', as_thread=True)
        else:
            logger.debug("No startup sound in config file")

        # load card id database
        cardid_database = self.nvm.load(cfg.getn('rfid', 'cardid_database'))

        logger.info("Init Jukebox RPC Server")
        rpcserver = RpcServer()

        rfid_reader = None
        # rfid_reader = RFID_Reader("RDM6300",{'numberformat':'card_id_float'})
        # rfid_reader = RFID_Reader("Fake", zmq_address='inproc://JukeBoxRpcServer', zmq_context=zmq.Context.instance())
        if rfid_reader is not None:
            rfid_reader.set_cardid_db(cardid_database)
            rfid_reader.reader.set_card_ids(list(cardid_database))     # just for Fake Reader to be aware of card ids
            rfid_thread = threading.Thread(target=rfid_reader.run)
        else:
            rfid_thread = None

        # initialize gpio
        # TODO: GPIO not yet integrated
        gpio_config = None
        if gpio_config is not None:
            pass
            # gpio_config = configparser.ConfigParser(inline_comment_prefixes=";")
            # gpio_config.read(self.config.get('GPIO', 'GPIO_CONFIG'))

            # phoniebox_function_calls = function_calls.phoniebox_function_calls()
            # gpio_controler = gpio_control(phoniebox_function_calls)

            # devices = gpio_controler.get_all_devices(config)
            # gpio_controler.print_all_devices()
            # gpio_thread = threading.Thread(target=gpio_controler.gpio_loop)
        else:
            gpio_thread = None

        # Start threads and RPC Server
        if rpcserver is not None:
            if gpio_thread is not None:
                logger.debug("Starting GPIO Thread")
                gpio_thread.start()
            if rfid_thread is not None:
                logger.debug("Starting RFID Thread")
                rfid_thread.start()

            logger.debug("Starting RPC Server ...")
            rpcserver.run()
