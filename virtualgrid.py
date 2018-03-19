#! /usr/bin/env python3

import random
import asyncio
import monome
import aiosc
import itertools
import re

DISCONNECTED, CONNECTED, READY = range(3)

class VirtualGridWrapper(monome.GridWrapper):
    def __init__(self, grid1, grid2):
        self.grid1 = grid1
        self.grid2 = grid2
        self.grid1.event_handler = self
        self.grid2.event_handler = self
        self.event_handler = None

    def connect(self):
        self.grid1.connect()
        self.grid2.connect()
        self.on_grid_ready()

    def on_grid_ready(self):
        #self.width = self.grid1.width + self.grid2.width
        self.width = 16 
        #self.height = self.grid1.height #this assumes spanning only horizontally 
        self.height = 8 
        #self.grid1.grid.send('/sys/rotation 180')
        #self.grid2.grid.send('/sys/rotation 270')
        self.event_handler.on_grid_ready()

    def on_grid_key(self, x, y, s):
        self.event_handler.on_grid_key(x, y, s)

    def on_grid_disconnect(self):
        self.event_handler.on_grid_disconnect()

    def led_set(self, x, y, s):
        if x < 8:
            self.grid1.led_set(x, y, s)
        else:
            r = x
            x = abs(y+8)
            y = r
            self.grid2.led_set(x, y, s)

    def led_all(self, s):
        self.grid1.led_all(s)
        self.grid2.led_all(s)

    #todo: split the data according to position
    def led_map(self, x_offset, y_offset, data):
        grid1_data = [0,0,0,0,0,0,0,0]
        grid2_data = [0,0,0,0,0,0,0,0]
        if len(data[0]) == 16:
            #need to split each row of data in half and then re-assemble into list of lists
            for i in range(8):
                grid1_data[i]=data[i][0:8]
                grid2_data[i]=data[i][8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1.led_map(x_offset, y_offset, grid1_data)
            self.grid2.led_map(x_offset, y_offset, grid2_data)
        if len(data[0]) == 8:
            self.grid1.led_map(x_offset, y_offset, data)
            self.grid2.led_map(x_offset, y_offset, data)

    #todo: split the data according to position
    def led_row(self, x_offset, y, data):
        grid1_data = [0,0,0,0,0,0,0,0]
        grid2_data = [0,0,0,0,0,0,0,0]
        if len(data) == 16:
            grid1_data=data[0:8]
            grid2_data=data[8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1.led_row(x_offset, y, grid1_data)
            self.grid2.led_row(x_offset, y, grid2_data)
        if len(data) == 8:
            self.grid1.led_row(x_offset, y, data)
            self.grid2.led_row(x_offset, y, data)

    def led_col(self, x, y_offset, data):
        if x < 8:
            self.grid1.led_col(x, y_offset, data)
        else:
            self.grid2.led_col(x-8, y_offset, data)

    def led_intensity(self, i):
        self.grid1.led_intensity(i)
        self.grid2.led_intensity(i)

    def led_level_set(self, x, y, l):
        if x < 8:
            self.grid1.led_level_set(x, y, l)
        else:
            r = x
            x = abs(y+8)
            y = r
            self.grid2.led_level_set(x, y, l)

    def led_level_all(self, l):
        self.grid1.led_level_all(l)
        self.grid2.led_level_all(l)

    def led_level_map(self, x_offset, y_offset, data):
        grid1_data = [0,0,0,0,0,0,0,0]
        grid2_data = [0,0,0,0,0,0,0,0]
        if len(data[0]) == 16:
            #need to split each row of data in half and then re-assemble into list of lists
            for i in range(8):
                grid1_data[i]=data[i][0:7]
                grid2_data[i]=data[i][8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1.led_map(x_offset, y_offset, grid1_data)
            self.grid2.led_map(x_offset, y_offset, grid2_data)
        if len(data[0]) == 8:
            self.grid1.led_map(x_offset, y_offset, data)
            self.grid2.led_map(x_offset, y_offset, data)

    def led_level_row(self, x_offset, y, data):
        self.grid1.led_level_row(x_offset, y, data)
        self.grid2.led_level_row(x_offset, y, data)

    def led_level_col(self, x, y_offset, data):
        if x < 8:
            self.grid1.led_level_col(x, y_offset, data)
        else:
            self.grid2.led_level_col(x-8, y_offset, data)

    def tilt_set(self, n, s):
        self.grid1.tilt_set(n, s)
        self.grid2.tilt_set(n, s)

# this wrapper makes adjustments for the orientation of the physical grid
# todo: make this responsive to a configuration file
class PhysicalGridWrapper_1(monome.GridWrapper):
    def __init__(self, grid):
        self.grid = grid
        self.grid.event_handler = self
        self.event_handler = None

    def on_grid_key(self, x, y, s):
        self.event_handler.on_grid_key(7-x, y, s) #rotate 180

    def led_set(self, x, y, s):
        self.grid.led_set(7-x, y, s)

    #rotates data 180
    def led_map(self, x_offset, y_offset, data):
        rotated1 = list(zip(*data[::-1]))
        rotated2 = list(zip(*rotated1[::-1]))
        #print("rotated 1")
        #for i in range(8):
        #    print (rotated1[i])
        #print("rotated 2")
        #print(rotated2)
        adjusted_data = rotated2
        self.grid.led_map(x_offset, y_offset, adjusted_data)

    def led_level_map(self, x_offset, y_offset, data):
        rotated1 = list(zip(*data[::-1]))
        rotated2 = list(zip(*rotated1[::-1]))
        #print("rotated 1")
        #for i in range(8):
        #    print (rotated1[i])
        #print("rotated 2")
        #print(rotated2)
        adjusted_data = rotated2
        self.grid.led_level_map(x_offset, y_offset, adjusted_data)

    def led_col(self, x, y_offset, data):
        #print("Grid 1: col data")
        #print(data)
        #rotated1 = list(zip(*data[::-1]))
        #rotated2 = list(zip(*rotated1[::-1]))
        #adjusted_data = rotated2
        self.grid.led_col(7-x, y_offset, data)
    
    #todo: make this responsive to rotation setting in config file 
    def led_row(self, x_offset, y, data):
        data.reverse() #rotate 180
        self.grid.led_row(x_offset, y, data)

# this wrapper makes adjustments for the orientation of the physical grid
# todo: make this responsive to a configuration file
class PhysicalGridWrapper_2(monome.GridWrapper):
    def __init__(self, grid):
        self.grid = grid
        self.grid.event_handler = self
        self.event_handler = None

    def on_grid_key(self, x, y, s):
        self.event_handler.on_grid_key(y+8, x, s) #rotate 90 and offset

    #rotates data 90
    def led_map(self, x_offset, y_offset, data):
        rotated1 = list(zip(*data[::-1]))
        adjusted_data = rotated1 
        self.grid.led_map(x_offset, y_offset, adjusted_data)

    #rotates data 90
    def led_level_map(self, x_offset, y_offset, data):
        rotated1 = list(zip(*data[::-1]))
        adjusted_data = rotated1 
        self.grid.led_level_map(x_offset, y_offset, adjusted_data)

    def led_col(self, x, y_offset, data):
        self.grid.led_row(x, y_offset+x, data)

    #todo: test this
    def led_row(self, x_offset, y, data):
        self.grid.led_col(x_offset+y, y, data)

class SpanningSerialOsc(monome.SerialOsc):
    def __init__(self, loop=None, autoconnect_app=None):
        super().__init__(loop, autoconnect_app)
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop
        self.autoconnect_app = autoconnect_app
        self.grid_list = []
        self.physical_grid1 = None
        self.physical_grid2 = None
        self.grid = None

    # check for connection of a physical device and call the appropriate connection routine
    # todo: make this responsive to a configuration file instead of hard coding grid ids
    def on_device_added(self, id, type, port):
        if id == "m40h-001": 
            asyncio.async(self.connect_physical_grid1(port))
        if id == "m40h-002": 
            asyncio.async(self.connect_physical_grid2(port))

    def on_device_removed(self, id, type, port):
        pass

    async def connect_physical_grid1(self, grid_port):
        transport, physical_grid = await self.loop.create_datagram_endpoint(monome.Grid, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', grid_port))
        print("connecting grid 1")
        self.physical_grid1 = PhysicalGridWrapper_1(physical_grid)
        self.physical_grid1.connect()

    async def connect_physical_grid2(self, grid_port):
        transport, physical_grid = await self.loop.create_datagram_endpoint(monome.Grid, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', grid_port))
        print("connecting grid 2")
        self.physical_grid2 = PhysicalGridWrapper_2(physical_grid)
        self.physical_grid2.connect()
        print("creating spanning grid")
        self.grid = VirtualGridWrapper(self.physical_grid1, self.physical_grid2)
        print("attaching app to grid")
        self.autoconnect_app.attach(self.grid)
