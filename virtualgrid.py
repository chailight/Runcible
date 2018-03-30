#! /usr/bin/env python3

import random
import asyncio
import monome
import aiosc
import itertools
import re
import numpy as np

DISCONNECTED, CONNECTED, READY = range(3)

class VirtualGridWrapper(monome.GridWrapper):
    def __init__(self, grid1, grid2):
        self.grid1 = grid1
        self.grid2 = grid2
        self.grid1.event_handler = self
        self.grid2.event_handler = self
        self.event_handler = None
        #self.grid1_data = [0,0,0,0,0,0,0,0]
        #self.grid2_data = [0,0,0,0,0,0,0,0]
        self.grid1_data = np.zeros((8,8))
        self.grid2_data = np.zeros((8,8))
        self.grid1_row_data = np.zeros((8,1))
        self.grid2_row_data = np.zeros((8,1))


    def connect(self):
        self.grid1.connect()
        self.grid2.connect()
        self.on_grid_ready()

    def on_grid_ready(self):
        #self.width = self.grid1.width + self.grid2.width
        self.width = 16
        #self.height = self.grid1.height #this assumes spanning only horizontally 
        self.height = 8
        self.event_handler.on_grid_ready()

    def on_grid_key(self, x, y, s):
        self.event_handler.on_grid_key(x, y, s)

    def on_grid_disconnect(self):
        self.event_handler.on_grid_disconnect()

    def led_set(self, x, y, s):
        if x < 8:
            self.grid1.led_set(x, y, s)
        else:
            #print("received",x,y)
            r = x
            x = abs(y+8)
            y = r-8
            #print("setting grid2",x,y)
            self.grid2.led_set(x, y, s)

    def led_all(self, s):
        self.grid1.led_all(s)
        self.grid2.led_all(s)

    #todo: split the data according to position
    def led_map(self, x_offset, y_offset, data):
        if len(data[0]) == 16:
            #need to split each row of data in half and then re-assemble into list of lists
            #for i in range(8):
            #    self.grid1_data[i]=data[i][0:8]
            #    self.grid2_data[i]=data[i][8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1_data, self.grid2_data = np.split(data,2)
            self.grid1.led_map(x_offset, y_offset, self.grid1_data.tolist())
            self.grid2.led_map(x_offset, y_offset, self.grid2_data.tolist())
        if len(data[0]) == 8:
            self.grid1.led_map(x_offset, y_offset, data)
            self.grid2.led_map(x_offset, y_offset, data)

    #todo: split the data according to position
    def led_row(self, x_offset, y, data):
        if len(data) == 16:
            self.grid1_row_data, self.grid2_row_data = np.split(data,2)
            #self.grid2_row_data=data[8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1.led_row(x_offset, y, self.grid1_data.tolist())
            self.grid2.led_row(x_offset, y, self.grid2_data.tolist())
        if len(data) == 8:
            self.grid1.led_row(x_offset, y, data)
            self.grid2.led_row(x_offset, y, data)

    def led_col(self, x, y_offset, data):
        if x < 8:
            self.grid1.led_col(x, y_offset, data)
        else:
            self.grid2.led_col(x-7, y_offset, data)

    def led_intensity(self, i):
        self.grid1.led_intensity(i)
        self.grid2.led_intensity(i)

    def led_level_set(self, x, y, l):
        if x < 8:
            self.grid1.led_level_set(x, y, l)
        else:
            r = x
            x = abs(y+7)
            y = r+1
            self.grid2.led_level_set(x, y, l)

    def led_level_all(self, l):
        self.grid1.led_level_all(l)
        self.grid2.led_level_all(l)

    def led_level_map(self, x_offset, y_offset, data):
        #grid1_data = [0,0,0,0,0,0,0,0]
        #grid2_data = [0,0,0,0,0,0,0,0]
        if len(data[0]) == 16:
            #need to split each row of data in half and then re-assemble into list of lists
            #for i in range(8):
            #    self.grid1_data[i]=data[i][0:8]
            #    self.grid2_data[i]=data[i][8:]
            #print(grid1_data)
            #print(grid2_data)
            self.grid1_data, self.grid2_data = np.split(np.asarray(data),2)
            self.grid1.led_map(x_offset, y_offset, self.grid1_data.tolist())
            self.grid2.led_map(x_offset, y_offset, self.grid2_data.tolist())
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
            self.grid2.led_level_col(x-7, y_offset, data)

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
        #rotated1 = zip(*data[::-1])
        #rotated2 = zip(*rotated1[::-1])
        #print("rotated 1")
        #for i in range(8):
        #    print (rotated1[i])
        #print("rotated 2")
        #print(rotated2)
        #adjusted_data = rotated2##
        print(np.fliplr(np.flipud(np.asarray(data))).shape)
        print(np.fliplr(np.flipud(np.asarray(data))).tolist())
        self.grid.led_map(x_offset, y_offset, np.fliplr(np.flipud(np.asarray(data))).tolist())

    def led_level_map(self, x_offset, y_offset, data):
        #rotated1 = zip(*data[::-1])
        #rotated2 = zip(*rotated1[::-1])
        #print("rotated 1")
        #for i in range(8):
        #    print (rotated1[i])
        #print("rotated 2")
        #print(rotated2)
        #adjusted_data = rotated2
        self.grid.led_level_map(x_offset, y_offset, np.fliplr(np.flipud(data)).tolist())

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

class myGridBuffer:
    def __init__(self, width, height):
        self.levels = [[0 for col in range(width)] for row in range(height)]
        self.width = width
        self.height = height

    def __and__(self, other):
        result = GridBuffer(self.width, self.height)
        for row in range(self.height):
            for col in range(self.width):
                result.levels[row][col] = self.levels[row][col] & other.levels[row][col]
        return result

    def __xor__(self, other):
        result = GridBuffer(self.width, self.height)
        for row in range(self.height):
            for col in range(self.width):
                result.levels[row][col] = self.levels[row][col] ^ other.levels[row][col]
        return result

    def __or__(self, other):
        result = GridBuffer(self.width, self.height)
        for row in range(self.height):
            for col in range(self.width):
                result.levels[row][col] = self.levels[row][col] | other.levels[row][col]
        return result

    def led_set(self, x, y, s):
        if x <= 1:
            self.led_level_set(x, y, s * 15)
        else:
            self.led_level_set(x, y, s)


    def led_all(self, s):
        self.led_level_all(s * 15)

    def led_map(self, x_offset, y_offset, data):
        for r, row in enumerate(data):
            self.led_row(x_offset, y_offset + r, row)

    def led_row(self, x_offset, y, data):
        for x, s in enumerate(data):
            self.led_set(x_offset + x, y, s)

    def led_col(self, x, y_offset, data):
        for y, s in enumerate(data):
            self.led_set(x, y_offset + y, s)

    def led_level_set(self, x, y, l):
        if x < self.width and y < self.height:
            self.levels[y][x] = l

    def led_level_all(self, l):
        for x in range(self.width):
            for y in range(self.height):
                self.levels[y][x] = l

    def led_level_map(self, x_offset, y_offset, data):
        for r, row in enumerate(data):
            self.led_level_row(x_offset, y_offset + r, row)

    def led_level_row(self, x_offset, y, data):
        if y < self.height:
            for x, l in enumerate(data[:self.width - x_offset]):
                self.levels[y][x + x_offset] = l

    def led_level_col(self, x, y_offset, data):
        if x < self.width:
            for y, l in enumerate(data[:self.height - y_offset]):
                self.levels[y + y_offset][x] = l

    def get_level_map(self, x_offset, y_offset):
        map = []
        for y in range(y_offset, y_offset + 8):
            row = [self.levels[y][col] for col in range(x_offset, x_offset + 8)]
            map.append(row)
        return map

    def get_binary_map(self, x_offset, y_offset):
        map = []
        for y in range(y_offset, y_offset + 8):
            row = [1 if self.levels[y][col] > 7 else 0 for col in range(x_offset, x_offset + 8)]
            map.append(row)
        return map

    def render(self, grid):
        for x_offset in [i * 8 for i in range(self.width // 8)]:
            for y_offset in [i * 8 for i in range(self.height // 8)]:
                grid.led_level_map(x_offset, y_offset, self.get_level_map(x_offset, y_offset))

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
        #print("setting rotation")
        #self.physical_grid1.grid.send('/sys/rotation 180')
        #self.physical_grid1.grid.rotation = 180
        #print("checking rotation")
        #self.physical_grid1.grid.send('/sys/info')

    async def connect_physical_grid2(self, grid_port):
        transport, physical_grid = await self.loop.create_datagram_endpoint(monome.Grid, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', grid_port))
        print("connecting grid 2")
        self.physical_grid2 = PhysicalGridWrapper_2(physical_grid)
        self.physical_grid2.connect()
        #self.physical_grid2.grid.send('/sys/rotation 270')
        #self.physical_grid2.grid.rotation = 270
        #print("checking rotation")
        #self.physical_grid2.grid.send('/sys/info')
        #print("creating spanning grid")
        self.grid = VirtualGridWrapper(self.physical_grid1, self.physical_grid2)
        print("attaching app to grid")
        self.autoconnect_app.attach(self.grid)
