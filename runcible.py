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
import monome
import spanned_monome
import clocks
#import synths
import pygame
import pygame.midi
from pygame.locals import *

def cancel_task(task):
    if task:
        task.cancel()


class GridStudies(spanned_monome.VirtualGrid):
    def __init__(self):
        super().__init__('runcible')

    def ready(self):
        print("Getting ready....")
        self.step = [[0 for col in range(self.width)] for row in range(6)]
        self.play_position = 0
        self.next_position = 0
        self.cutting = False
        self.loop_start = 0
        self.loop_end = self.width - 1
        self.keys_held = 0
        self.key_last = 0

        asyncio.async(self.play())

    @asyncio.coroutine
    def play(self):
        while True:
            if self.cutting:
                self.play_position = self.next_position
            elif self.play_position == self.width - 1:
                self.play_position = 0
            elif self.play_position == self.loop_end:
                self.play_position = self.loop_start
            else:
                self.play_position += 1

            # TRIGGER SOMETHING
            for y in range(6):
                if self.step[y][self.play_position] == 1:
                    self.trigger(y)

            self.cutting = False
            self.draw()

            yield from asyncio.sleep(0.1)

    def trigger(self, i):
        print("triggered", i)

    def draw(self):
        buffer = monome.LedBuffer(self.width, self.height)

        # display steps
        for x in range(self.width):
            # highlight the play position
            if x == self.play_position:
                highlight = 4
            else:
                highlight = 0

            for y in range(6):
                buffer.led_level_set(x, y, self.step[y][x] * 11 + highlight)

        # draw trigger bar and on-states
        for x in range(self.width):
            buffer.led_level_set(x, 6, 4)

        for y in range(6):
            if self.step[y][self.play_position] == 1:
                buffer.led_level_set(self.play_position, 6, 15)

        # draw play position
        buffer.led_level_set(self.play_position, 7, 15)

        # update grid
        print("rendering: ", buffer.get_level_map(0,0))
        buffer.render(self)

    #def grid_key(self, x, y, s):
    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        # toggle steps
        if s == 1 and y < 6:
            self.step[y][x] ^= 1
            self.draw()
        # cut and loop
        elif y == 7:
            self.keys_held = self.keys_held + (s * 2) - 1
            # cut
            if s == 1 and self.keys_held == 1:
                self.cutting = True
                self.next_position = x
                self.key_last = x
            # set loop points
            elif s == 1 and self.keys_held == 2:
                self.loop_start = self.key_last
                self.loop_end = x


#the sequencer logic, based on ansible kria
class Runcible(spanned_monome.VirtualGrid):
    def __init__(self, clock, ticks, midi_out,channel_out,clock_out,other):
        super().__init__('runcible')
        self.clock = clock
        self.ticks = ticks 
        self.midi_out = midi_out
        self.channel = channel_out
        self.clock_ch= clock_out
        #self.other = other 

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
        #pygame.init()
        #pygame.midi.init()
        #self.midiport = 2
        #print ("using output_id :%s:" % self.midiport)
        #self.midi_out = pygame.midi.Output(self.midiport, 0)
        asyncio.async(self.play())

    def disconnect(self):
        self.led_all(0)

    @asyncio.coroutine
    def play(self):
        self.current_pos = yield from self.clock.sync()
        self.play_position = (self.current_pos//self.ticks)%16
        while True:
            if ((self.current_pos//self.ticks)%16) < 8:
                #print("G1:",(self.current_pos//self.ticks)%16)
                self.draw()
                # TRIGGER SOMETHING
                for y in range(self.height):
                    #print("y:",y, "pos:", self.play_position)
                    if self.step_ch1[y][self.play_position] == 1:
                        #print("Grid 1:", self.play_position,abs(y-7))
                        asyncio.async(self.trigger(abs(y-7),0))
                    if self.step_ch2[y][self.play_position] == 1:
                        #print("Grid 1:", self.play_position,abs(y-7))
                        asyncio.async(self.trigger(abs(y-7),1))

#                if self.cutting:
#                    self.play_position = self.next_position
#                elif self.play_position == self.width - 1:
#                    self.play_position = 0
#                elif self.play_position == self.loop_end:
#                    self.play_position = self.loop_start
#                else:
#                    self.play_position += 1

                self.cutting = False
            else:
                #buffer = monome.LedBuffer(self.width, self.height)
                #buffer.led_level_set(0, 0, 0)
                self.draw()

            #yield from asyncio.sleep(0.1)
            asyncio.async(self.clock_out())
            yield from self.clock.sync(self.ticks)
            self.current_pos = yield from self.clock.sync()
            self.play_position = (self.current_pos//self.ticks)%16

# remove correction
    #def gridToSpan(self,x,y):
    #    #return [abs(y-7),x]
    #    return [abs(x-7),abs(y-7)]
         
    #def spanToGrid(self,x,y):
    #    #return [y,abs(x-7)]
    #    return [abs(x-7),abs(y-7)]

    @asyncio.coroutine  #make this take two channels simultaneously as I think there's timing issues with calling it twice for the same "instant"
    def trigger(self, i, ch):
        #print("Grid1", i)
        self.current_note = 40+i
        #print("G1: note: " + str(self.current_note) + " channel: " + str(self.channel))
        self.midi_out.note_on(self.current_note, 60, self.channel+ch)
        yield from self.clock.sync(self.ticks)
        #yield from asyncio.sleep(0.01)
        self.midi_out.note_off(self.current_note, 0, self.channel+ch)

    @asyncio.coroutine
    def clock_out(self):
        #print("Grid1", i)
        #self.midi_out.note_on(40, 60, self.clock_ch)
        #print("G1: clock on "  + " channel: " + str(self.clock_ch))
        yield from self.clock.sync(self.ticks)
        #yield from asyncio.sleep(0.01)
        #self.midi_out.note_off(40, 0, self.clock_ch)
        #print("G1: clock off "  + " channel: " + str(self.clock_ch))

    def draw(self):
        buffer = monome.LedBuffer(self.width, self.height)

        # display steps
        for x in range(self.width):
            # highlight the play position
            if x == self.play_position:
                highlight = 4
            else:
                highlight = 0

            for y in range(self.height):
                render_pos = self.spanToGrid(x,y)
                if self.current_channel == 1:
                    buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch1[y][x] * 11 + highlight)
                else:
                    buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch2[y][x] * 11 + highlight)

        # draw trigger bar and on-states
#        for x in range(self.width):
#            buffer.led_level_set(x, 6, 4)

#        for y in range(6):
#            if self.step_ch1[y][self.play_position] == 1:
#                buffer.led_level_set(self.play_position, 6, 15)

        # draw play position
        #current_pos = yield from self.clock.sync()
        print("runcible:",(self.current_pos//self.ticks)%16)
        render_pos = self.spanToGrid(self.play_position, 0)
        if ((self.current_pos//self.ticks)%16) < 8:
 #           print("Pos",self.play_position)
            buffer.led_level_set(render_pos[0], render_pos[1], 15)
        else:
            buffer.led_level_set(render_pos[0], render_pos[1], 0) # change this to restore the original state of the led


        # update grid
        buffer.render(self)

    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        #self.led_set(x, y, s)

        # toggle steps
        if s == 1 and y > 0:
            if self.current_channel == 1:
                self.step_ch1[y][x] ^= 1
            else:
                self.step_ch2[y][x] ^= 1
            self.draw()
        elif y == 0:
            if x == 0:
                self.current_channel = 1
                #self.other.set_channel(1)
            elif x == 1:
                self.current_channel = 2
                #self.other.set_channel(2)
        # cut and loop
            self.keys_held = self.keys_held + (s * 2) - 1
            # cut
            if s == 1 and self.keys_held == 1:
                self.cutting = True
                self.next_position = x
                self.key_last = x
            # set loop points
            elif s == 1 and self.keys_held == 2:
                self.loop_start = self.key_last
                self.loop_end = x


class Test1(monome.Monome):
    def __init__(self):
        super().__init__('/hello')

    def ready(self):
        self.x_offset=0

    def gridToSpan(self,x,y):
        return [x,y]
        #return [abs(y-7),x]
    #    return [abs(x-7),abs(y-7)]

    def spanToGrid(self,x,y):
        return [x,y]
        #return [y,abs(x-7)]
    #    return [abs(x-7),abs(y-7)]

    # replace with VirtualGrid code??
    def grid_key(self, x, y, s):
        self.led_set(x, y, s)
    #    span_coord = self.gridToSpan(x,y) 
    #    print("grid 1: ", x,y, span_coord, self.spanToGrid(span_coord[0],span_coord[1]))

class Test2(monome.Monome):
    def __init__(self):
        super().__init__('/hello')

    def ready(self):
        self.x_offset=8

    def gridToSpan(self,x,y):
        return [abs(y+self.x_offset),abs(x-7)]

    def spanToGrid(self,x,y):
        return [abs(y-7),abs(x-self.x_offset)]

    def grid_key(self, x, y, s):
        self.led_set(x, y, s)
        span_coord = self.gridToSpan(x,y) 
        print("grid 2: ", x,y, span_coord, self.spanToGrid(span_coord[0],span_coord[1]))

class Test3(spanned_monome.VirtualGrid):
    def __init__(self):
        super().__init__('runcible') #maybe just setting the name of the virtual grid here allows the size to be looked up?

    def ready(self):
        self.x_offset=0

    #def grid_key(self, x, y, s):
    #    x, y, s = self.translate_key(x, y, s)
    #    self.led_set(x, y, s)
        #print("runcible: ", x,y)

    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        data1 = [[1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        data2 = [[0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [1,1,1,1,1,1,1,1],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]

        clear_all = [[0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0],
                [0,0,0,0,0,0,0,0]]
        if x == 0 and y == 0:
            self.led_map(0,0,data1)
            self.led_map(8,0,data2)
        else:
            self.led_map(0,0,clear_all)
            self.led_map(8,0,clear_all)
            self.led_set(x, y, s)

class Test4(spanned_monome.VirtualGrid):
    def __init__(self):
        super().__init__('/hello')
        aiosc(('127.0.0.1', 9000), '/hello', 'world')

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    pygame.init()
    pygame.midi.init()
    device_count = pygame.midi.get_count()
    #print (pygame.midi.get_default_output_id())
    midiport = 0
    clock_out = 3
    info = list()
    for i in range(device_count):
       info = pygame.midi.get_device_info(i)
       print (str(i) + ": " + str(info[1]) + " " + str(info[2]) + " " + str(info[3]))
       if 'MIDI 6' in str(info[1]) and info[3] == 1: 
           midiport = i 
       #if 'MIDI 1' in str(info[1]) and info[3] == 0: 
       #   clock_out = i 
    print ("using output_id : %s " % midiport)
    midi_out = pygame.midi.Output(midiport, 0)
    print ("using clock source: %s " % clock_out)
    channel_out = 2
    page = 1
    #midi_out=None

    # create clock
    #coro = loop.create_datagram_endpoint(clocks.FooClock, local_addr=('127.0.0.1', 9000))
    #transport, clock = loop.run_until_complete(coro)
    #clock = clocks.InaccurateTempoClock(120)
    #g1 = lambda: GridSeq1(clock,24,midi_out,channel_out,clock_out,page)
    #g2 = lambda: GridSeq2(clock,24,midi_out,channel_out,clock_out,page)

    clock = clocks.RtMidiClock()
    #g1 = lambda: None 
    #g2 = lambda: GridSeq2(clock,6,midi_out,channel_out,clock_out,g1)
    g1 = lambda: Runcible(clock,6,midi_out,channel_out,clock_out,None)
#    r1 = lambda: Test1() 
#    r2 = lambda: Test2() 
    sg1 = lambda: Test3() 
    sg2 = lambda: GridStudies() 

    #g1 = lambda: Test1()
    #g2 = lambda: Test2()
    #coro = monome.create_serialosc_connection({
    #      'm40h-001': g1,
    #      'm40h-002': g2,
    #}, loop=loop)

    #coro, g1_coro  = monome.create_spanned_serialosc_connection({
    coro = spanned_monome.create_spanned_serialosc_connection({
          'runcible': sg2,
    }, loop=loop)

    # create synth
#    coro = loop.create_datagram_endpoint(synths.Renoise, local_addr=('127.0.0.1', 0), remote_addr=('127.0.0.1', 8001))
#    transport, renoise = loop.run_until_complete(coro)

#    coro = monome.create_serialosc_connection(lambda: Flin(clock, renoise, 0))
    #g1_serialosc = loop.run_until_complete(g1_coro)
    serialosc = loop.run_until_complete(coro)

    try: # can we all methods in the app which handle page setting updates? If so, then we just need something which returns a value to the main without breaking the loop
        loop.run_forever()
    except KeyboardInterrupt:
        for apps in serialosc.app_instances.values():
            for app in apps:
                app.disconnect()
        print('kthxbye')

