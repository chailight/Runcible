#! /usr/bin/env python3

#RUNCIBLE - a raspberry pi / python sequencer for spanned 40h monomes inspired by Ansible Kria
#TODO:
#check for cutting / looping input on both grids
#solve message passing from one grid to another - can there be a global variable or some kind of handler?
#add second channel to Grid2 as per Grid1, based on setting the current channel via global variable or handler
#add input/display for duration, velocity, octave and probability, as per kria
#add presets: store and recall - likewise a global preset value? 
#add persistence of presets
#add scale setting for both grids - global value?

import asyncio
import aiosc

import clocks
#import synths
import pygame
import pygame.midi
from pygame.locals import *

class VirtualGrid(aiosc.OSCProtocol):
    def __init__(self,id, xsize, ysize, port=0):
        #self.prefix = 'runcible'
        self.id = id
        self.width = xsize
        self.height = ysize
        self.rotation = None
        self.varibright = False
        #self.app_host = DEFAULT_APP_HOST
        #self.app_port = DEFAULT_APP_PORT
        self.prefix = id
        super().__init__(handlers={
            '/sys/exit': self.exit,
            '/sys/disconnect': lambda *args: self.disconnect,
            '/sys/{id,size,host,port,prefix,rotation}': self.sys_info,
            '/*/grid/key': self.grid_key,
            '/{}/tilt'.format(self.prefix): lambda addr, path, n, x, y, z: self.tilt(n, x, y, z),
            '//*': self.echo,
        })
        print("Virtual Grid: ", self.id, "X: ", self.width, "Y: ", self.height)

    def exit(self, *args):
        asyncio.get_event_loop().stop()

    def echo(self, addr, path, *args):
        print("incoming message from {}: {} {}".format(addr, path, args))
        # echo the message
        #self.send(path, *args, addr=addr)

    #def connection_made(self, transport):
    #    super().connection_made(transport)
    #    self.host, self.port = transport.get_extra_info('sockname')
    #    self.connect()

    def connect(self):
        pass
        #self.send('/sys/host', self.host)
        #self.send('/sys/port', self.port)
        #self.send('/sys/prefix', self.prefix)
        #self.send('/sys/info', self.host, self.port)

    def disconnect(self):
        self.transport.close()

    def sys_info(self, addr, path, *args):
        if path == '/sys/id':
            self.id = args[0]
        elif path == '/sys/size':
            self.width, self.height = (args[0], args[1])
        elif path == '/sys/rotation':
            self.rotation = args[0]

        # TODO: refine conditions for reinitializing
        # in case rotation, etc. changes
        # Note: arc will report 0, 0 for its size
        if all(x is not None for x in [self.id, self.width, self.height, self.rotation]):
            if re.match('^m\d+$', self.id):
                self.varibright = True
            self.ready()

    def ready(self):
        print ("using grid on port :%s" % self.id)
        self.current_pos = 0
        self.step_ch1 = [[0 for col in range(self.width)] for row in range(self.height)]
        self.step_ch2 = [[0 for col in range(self.width)] for row in range(self.height)]
        self.play_position = 0
        self.next_position = 0
        self.cutting = False
        self.loop_start = 0
        self.loop_end = self.width - 1
        self.keys_held = 0
        self.key_last = 0
        self.current_channel = 1
        #asyncio.async(self.play())

    def grid_key(self, addr, path, *args):
        #translate grid_key from device grid coords to spanned grid coords
        #print(args)
        x, y, s = args
        #print(args[0])
        #x,y,s = str(args[0]).split()
        print("raw grid_key: ",path,x,y,s)
        if path == '/m40h-001/grid/key':
            x=abs(x-7)
            print("spanned grid_key: ",x,y,s)
        elif path == '/m40h-002/grid/key':
            r = x
            x = y+8
            y = r
            print("spanned grid_key: ",x,y,s)

        self.led_set(x,y,s)

    def tilt(self, n, x, y, z):
        pass

    def led_set(self, x, y, s):
        #translate grid_key from spanned grid coords to device grid coords
        if x < 8: 
            x = abs(7-x)
            print("sending /mh40h-001/grid/led/set", x,y,s)
            path = '/m40h-001/grid/led/set'
            asyncio.async(aiosc.send(('127.0.0.1', 8000), path, x, y, s))
        else:
            r = y
            y = abs(x-8)
            x = r
            print("sending /m40h-002/grid/key ", x,y,s)
            path = '/m40h-002/grid/led/set'
            asyncio.async(aiosc.send(('127.0.0.1', 8001), path, x, y, s))
        #self.send('/{}/grid/led/set'.format(self.prefix), x, y, s)
        #send messages to spanned grids

    def led_all(self, s):
        pass
        #self.send('/{}/grid/led/all'.format(self.prefix), s)

    def led_map(self, x_offset, y_offset, data):
        args = [pack_row(data[i]) for i in range(8)]
        #self.send('/{}/grid/led/map'.format(self.prefix), x_offset, y_offset, *args)

    def led_row(self, x_offset, y, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        #self.send('/{}/grid/led/row'.format(self.prefix), x_offset, y, *args)

    def led_col(self, x, y_offset, data):
        args = [pack_row(data[i*8:(i+1)*8]) for i in range(len(data) // 8)]
        #self.send('/{}/grid/led/col'.format(self.prefix), x, y_offset, *args)

    def led_intensity(self, i):
        pass
        #self.send('/{}/grid/led/intensity'.format(self.prefix), i)

    def led_level_set(self, x, y, l):
        if self.varibright:
            pass
        #    self.send('/{}/grid/led/level/set'.format(self.prefix), x, y, l)
        else:
            pass
        #    self.led_set(x, y, l >> 3 & 1)

    def led_level_all(self, l):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/all'.format(self.prefix), l)
        else:
            pass
            #self.led_all(l >> 3 & 1)

    def led_level_map(self, x_offset, y_offset, data):
        if self.varibright:
            args = itertools.chain(*data)
            #self.send('/{}/grid/led/level/map'.format(self.prefix), x_offset, y_offset, *args)
        else:
            pass
            #self.led_map(x_offset, y_offset, [[l >> 3 & 1 for l in row] for row in data])

    def led_level_row(self, x_offset, y, data):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/row'.format(self.prefix), x_offset, y, *data)
        else:
            pass
            #self.led_row(x_offset, y, [l >> 3 & 1 for l in data])

    def led_level_col(self, x, y_offset, data):
        if self.varibright:
            pass
            #self.send('/{}/grid/led/level/col'.format(self.prefix), x, y_offset, *data)
        else:
            pass
            #self.led_col(x, y_offset, [l >> 3 & 1 for l in data])

    def tilt_set(self, n, s):
        pass
        #self.send('/{}/tilt/set'.format(self.prefix), n, s)


loop = asyncio.get_event_loop()
g1 = lambda: VirtualGrid('runcible',16,8)
coro = loop.create_datagram_endpoint(g1, local_addr=('127.0.0.1', 9000))
transport, protocol = loop.run_until_complete(coro)

loop.run_forever()
