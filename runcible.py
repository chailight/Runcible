#! /usr/bin/env python3
#RUNCIBLE - a raspberry pi / python sequencer for spanned 40h monomes inspired by Ansible Kria
#TODO:
#tweak note duration - get the right scaled values 
#fix loop setting and display on all screens
#make looping independent for each parameter
#add a loop phase reset input as per kria
#add preset copy
#add note mutes for drum channel?
#add input/display for probability, as per kria - implement a next_note function which returns true or false based on probability setting for that track at that position
#at this stage, for polyphonic tracks, probabilities are per position - like velocity - not per note 
#enable a per channel transpose setting? 
#add scale editing 
#adjust preset selection to allow for meta sequencing
#fix display of current preset
#fix cutting - has to do with keys held
#enable looping around the end of the loop start_loop is higher than end_loop
#add pattern cue timer
#add meta mode (pattern sequencing)
#consider per row velocity settings for polyphonic tracks
#adjust use of duration settings 1/8, 1/16 & 1/32 notes?  (6 duration positions = 1/32, 1/16, 1/8, 1/4, 1/2, 1)
#make note entry screen monophonic? - clear off other notes in that column if new note is entered - this should be configurable maybe on trigger page?
#add settings screen with other adjustments like midi channel for each track?
#fix pauses - network? other processes?
#fix clear all on disconnect
#fix hanging notes on sequencer stop? how? either note creation becomes atomic or else there's a midi panic that gets called when the clock stops? maybe just close the midi stream?

import pickle
import os
import sys
import subprocess
import asyncio
import monome
import spanned_monome
import clocks
import rtmidi2
from enum import Enum

def cancel_task(task):
    if task:
        task.cancel()

class Modes(Enum):
    mTr = 0
    mNote = 1
    mOct = 2
    mDur = 3
    mVel = 4
    mScale = 5
    mPattern = 6

class ModModes(Enum):
    modNone = 1
    modLoop = 2
    modTime = 3
    modProb = 4

class Note:
    def __init__(self,channel_inc = 0, pitch = 0, velocity = 0, duration=0):
        self.channel_inc = channel_inc #this is the increment to the global base channel
        self.pitch = pitch
        self.velocity = velocity
        self.duration = duration

    def decrement_duration(self):
        if self.duration > 0: 
            self.duration = self.duration - 1

class Track:
    def __init__(self,track_id):
        self.num_params = 4
        self.tr = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        self.octave = [0 for i in range(16)]
        self.note = [list() for i in range(16)]
        self.duration = [1 for i in range(16)]
        self.velocity = [3 for i in range(16)]
        self.params = [[0] * self.num_params for i in range (16)] #initialise a 4x16 array
        self.dur_mul = 1; #duration multiplier
        self.lstart = [0,0,0,0,0]
        self.lend = [15,15,15,15,15]
        self.last_pos = [15,15,15,15,15]
        self.next_pos = [15,15,15,15,15]
        self.swap = [[0] * self.num_params] # what is this actually for?
        self.tmul = [1,1,1,1,1]
        self.pos = [0,0,0,0,0] #current position for each parameter in each track - replaces play_position
        self.pos_mul = [0,0,0,0,0]  #something to do with the time multiplier
        self.pos_reset = False
        self.track_id = track_id
        self.play_position = 0 # will switch to position for each parameter
        self.next_position = 0 # will switch to position for each parameter
        self.loop_start = 0  # will eventually switch to loop start / end per parameter but keep it simple for now
        self.loop_end = 15
        self.loop_count = 0
        self.loop_first = 0
        self.loop_last = 0
        self.loop_edit = 0
        self.scale_toggle = 1
        self.track_mute = 0


class Pattern:
    def __init__(self,pattern_id):
        self.pattern_id = pattern_id
        self.tracks = [Track(i) for i in range(4)]
        self.step_ch1 = [[0 for col in range(16)] for row in range(8)] #used for display of notes
        self.step_ch2 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch3 = [[0 for col in range(16)] for row in range(8)]
        self.step_ch4 = [[0 for col in range(16)] for row in range(8)]


class Preset:
    def __init__(self):
        self.patterns = [Pattern(i) for i in range(16)]
        self.current_pattern = 0
        self.meta_pat = [[0] * 64]
        self.meta_steps = [[0] * 64]
        self.meta_start = 0
        self.meta_end = 0
        self.meta_len = 0
        self.meta_lswap = 0
        self.glyph = [[0] * 8]
        # this needs to be in the Preset into state so custom scales are stored
        self.scale_data = [[48,2,2,1,2,2,2,1],
                           [48,2,1,2,2,1,2,2],
                           [48,2,2,1,2,2,2,1],
                           [48,2,1,2,2,2,1,2],
                           [48,1,2,2,2,1,2,2],
                           [48,2,2,2,1,2,2,1],
                           [48,2,2,1,2,2,1,2],
                           [48,2,1,2,2,1,2,2],
                           [48,1,2,2,1,2,2,2],
                           [48,3,2,2,3,2,3,2],
                           [48,2,2,3,2,3,2,2],
                           [48,3,2,1,1,3,2,3],
                           [48,1,3,1,2,1,2,2],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0],
                           [48,0,0,0,0,0,0,0]]

class State:
    def __init__(self):
        self.clock_period = 0
        self.current_preset_id = 0
        self.note_sync = True
        self.loop_sync = 0
        self.cue_div = 0
        self.cue_steps = 0
        self.meta = 0
        self.presets = [Preset() for i in range(15)]

#runcible sequencer, based on ansible kria
class Runcible(spanned_monome.VirtualGrid):
    def __init__(self, clock, ticks, midi_out,channel_out,clock_out,other):
        super().__init__('runcible')
        self.clock = clock
        self.ticks = ticks
        self.midi_out = midi_out
        self.channel = channel_out
        self.clock_ch = clock_out
        self.cur_scale = [0,0,0,0,0,0,0,0]
        self.cur_scale_id = 0
        self.cur_trans = 0
        self.k_mode = Modes.mNote
        self.k_mod_mode = ModModes.modNone
        self.state = State()
        #self.note_on = [[Note()] for i in range(96)] #full resolution
        self.note_on = [[Note()] for i in range(16)]
        #self.note_off = [[Note()] for i in range(96)]
        self.note_off = [[Note()] for i in range(16)]
        self.duration_timers = [Note()] 
        #call ready() directly because virtual device doesn't get triggered
        self.pickle_file_path = "/home/pi/monome/runcible/runcible.pickle" 
        self.ctrl_keys_held = 0
        self.ctrl_keys_last = list()
        self.ready()

    def ready(self):
        print ("using grid on port :%s" % self.id)
        self.current_pos = 0
        #self.play_position = [0,0,0,0] # one position for each track
        #self.fine_play_position = 0
        #self.next_position = [0,0,0,0]
        self.cutting = False
        #remove loop from main logic
        #self.loop_start = [0,0,0,0]
        #self.loop_end = [self.width - 1, self.width -1, self.width -1, self.width -1]
        #self.loop_length = [self.width, self.width, self.width, self.width]
        self.keys_held = 0
        self.key_last = [0,0,0,0]

        self.current_pitch = [0,0,0,0]
        self.current_oct = [0,0,0,0]
        self.current_dur = [0,0,0,0]
        self.current_vel = [0,0,0,0]

        if os.path.isfile(self.pickle_file_path):
            self.restore_state()
        self.current_preset = self.state.presets[0]
        self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
        self.current_track = self.current_pattern.tracks[0]
        self.current_track_id = self.current_pattern.tracks[0].track_id
        self.calc_scale(self.cur_scale_id)
        self.frame_dirty = False 
        asyncio.async(self.play())

    def dummy_disconnect(self):
        print("Disconnecting... thanks for playing!")

    def disconnect(self):
        print("Disconnecting... thanks for playing!")
        self.midi_out.close_port()
        self.save_state()
        super().disconnect()
        sys.exit(0)
        #command = "/usr/bin/sudo /sbin/shutdown -h now"
        #process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
        #output = process.communicate()[0]
        #print(output)

    def next_step(self, track, parameter):
       #print("track.pos_mul: ", parameter, track.pos_mul[parameter])
       track.pos_mul[parameter] = int(track.pos_mul[parameter]) + 1

       if track.pos_mul[parameter] >= self.current_pattern.tracks[track.track_id].tmul[parameter]:
            if track.pos[parameter] == self.current_pattern.tracks[track.track_id].lend[parameter]:
                track.pos[parameter] = self.current_pattern.tracks[track.track_id].lstart[parameter]
            else:
                track.pos[parameter] = int(track.pos[parameter]) + 1
                if track.pos[parameter] > 15:
                    track.pos[parameter] = 0
            track.pos_mul[parameter] = 0
            # add probabilities
            return True
       else:
            return False

    @asyncio.coroutine
    def play(self):
        self.current_pos = yield from self.clock.sync()
        for t in self.current_pattern.tracks:
            #self.loop_length[t] = abs(self.loop_end[self.current_track] - self.loop_start[t])+1
            t.loop_length = abs(t.loop_end - t.loop_start)+1
            t.play_position = (self.current_pos//self.ticks)%t.loop_length + t.loop_start
        while True:
            self.frame_dirty = True #because if nothing else has happend, at least the position marker has moved
            #print("calling draw at position: ", self.current_pos)
            self.draw()
            # TRIGGER SOMETHING
            for track in self.current_pattern.tracks:
                if self.next_step(track, Modes.mNote.value):
                    if track.note[track.pos[Modes.mNote.value]][0]:
                        self.current_pitch = track.note[track.pos[Modes.mNote.value]][0] #need to adjust for polyphonic
                    print("current_pitch: ", self.current_pitch)
                if self.next_step(track, Modes.mOct.value):
                    self.current_oct = track.octave[track.pos[Modes.mOct.value]]
                    print("current_oct: ", self.current_oct)
                if self.next_step(track, Modes.mDur.value):
                    self.current_dur = track.duration[track.pos[Modes.mDur.value]]
                    print("current_dur: ", self.current_dur)
                if self.next_step(track, Modes.mVel.value):
                    self.current_vel = track.velocity[track.pos[Modes.mVel.value]]
                    print("current_vel: ", self.current_vel)
                if self.next_step(track, Modes.mTr.value):
                    #if track.tr[track.play_position] == 1:
                    if track.tr[track.pos[Modes.mTr.value]] == 1:
                        #for i in range(len(track.note[track.play_position])):
                        for i in range(len(track.note[track.pos[Modes.mTr.value]])): #this needs to be fixed so that polyphonic mode forces track sync
                            # add toggles here for loop sync - if track then set position to mTr.value, else set to parameter 
                            if track.scale_toggle:
                                #current_note = self.cur_scale[track.note[track.play_position][i]-1]+track.octave[track.play_position]*12
                                #print("track.pos: ", track.pos[note_pos], "i: ", i, "current_note: ", track.note[track.pos[note_pos]])
                                current_note = self.cur_scale[self.current_pitch-1] + self.current_oct*12 #may have to introduce a check for self.current_pitch not being zero
                                print("input note: ", self.current_pitch, "current note: ", current_note)
                            else:
                                #set the note to an increment from some convenient base
                                #current_note = track.note[track.play_position][i]+35+track.octave[track.play_position]*12
                                #current_note = track.note[track.pos[note_pos]][i]+35+track.octave[track.pos[oct_pos]]*12
                                current_note = self.current_pitch+35 + self.current_oct*12
                                print("input note: ", self.current_pitch, "current note: ", current_note)

                            #print("input note: ", track.note[track.playposition[i], "scaled_note: ", current_note)
                            scaled_duration = 0
                            #entered_duration = track.duration[track.play_position]
                            entered_duration = self.current_dur
                            if entered_duration == 1:
                                scaled_duration = 2
                            if entered_duration == 3:
                                scaled_duration = 4
                            if entered_duration == 3:
                                scaled_duration =  6
                            if entered_duration == 4:
                                scaled_duration = 8
                            elif entered_duration == 5:
                                scaled_duration = 10
                            elif entered_duration == 6:
                                scaled_duration = 12
                            #velocity = track.velocity[track.play_position]*20
                            #velocity = track.velocity[track.pos[Modes.mTr.value]]*20
                            velocity = self.current_vel*20
                            #print("velocity: ", velocity)
                            #velocity = 65
                            #print("entered: ", entered_duration, "scaled duration: ", scaled_duration)
                            if not track.track_mute:
                                #self.insert_note(track.track_id, track.play_position, current_note, velocity, scaled_duration) # hard coding velocity
                                self.insert_note(track.track_id, track.pos[Modes.mTr.value], current_note, velocity, scaled_duration) # hard coding velocity
                                #print("calling insert note: ",current_note, velocity,scaled_duration, "on track: ", track.track_id, "at pos: ", track.pos[Modes.mTr.value])

                    self.cutting = False

            #asyncio.async(self.trigger())
            asyncio.async(self.trigger())
            #asyncio.async(self.clock_out())
            yield from self.clock.sync(self.ticks//2)
            self.current_pos = yield from self.clock.sync()
            for track in self.current_pattern.tracks:
                track.loop_length = abs(track.loop_end - track.loop_start)+1
                track.play_position = (self.current_pos//self.ticks)%track.loop_length + track.loop_start

    def insert_note(self,track,position,pitch,velocity,duration):
        asyncio.async(self.set_note_on(track,position,pitch,velocity,duration))
        #self.insert_note_off(track,(position+duration)%16,pitch)
        #print("setting note on at: ", position, " + ", self.current_pattern.tracks[track].duration[position])
        #print("setting note off at: ", position, " + ", self.current_pattern.tracks[track].duration[position])
        #asyncio.async(self.set_note_off_timer(track,duration,pitch))

    def insert_note_on(self,track,position,pitch,velocity):
        already_exists = False
        for n in self.note_on[position]:
            if n.pitch == pitch:
                already_exists = True
                print("note on exists", self.channel + track, pitch, "at position: ", position)
        if not already_exists:
            new_note = Note(track,pitch,velocity)
            self.note_on[position].append(new_note)
            #pos = yield from self.clock.sync()
            print("setting note on ", self.channel + track, pitch, "at pos: ", position)

    def insert_note_off(self,track,position,pitch):
        already_exists = False
        for n in self.note_off[position]:
            if n.pitch == pitch:
                already_exists = True
                print("note off exists", self.channel + track, pitch, "at position: ", position)
        if not already_exists:
            new_note = Note(track,pitch,0)
            self.note_off[position].append(new_note)
            #pos = yield from self.clock.sync()
            print("setting note off ", self.channel + track, pitch, "at pos: ", position)

    @asyncio.coroutine
    def set_note_on(self,track,position,pitch,velocity,duration):
        already_exists = False
        for n in self.note_on[position]:
            if n.pitch == pitch:
                already_exists = True
            #    print("note on exists", self.channel + track, pitch, "at position: ", position)
        if not already_exists:
            new_note = Note(track,pitch,velocity,duration)
            self.note_on[position].append(new_note)
            #pos = yield from self.clock.sync()
            #self.midi_out.send_noteon(self.channel + track, pitch, velocity)
            self.duration_timers.append(new_note) # add this to the list of notes to track for when they end
            #print("set note on: ", self.channel + track, pitch, "at: ", position)

    @asyncio.coroutine
    def set_note_off_timer(self,track,duration,pitch):
        pos = yield from self.clock.sync(duration*4)
        self.midi_out.send_noteon(self.channel + track, pitch,0)
        print("note off timer", self.channel + track, pitch, "at: ", pos%16)

    def calc_scale(self, s):
        self.cur_scale[0] = self.current_preset.scale_data[s][0] + self.cur_trans
        for i1 in range(1,8):
            self.cur_scale[i1] = self.cur_scale[i1-1] + self.current_preset.scale_data[s][i1]


    @asyncio.coroutine
    def trigger(self):
        #print("trigger called")
        # play all notes in this position
        for t in self.current_pattern.tracks:
            #for note in self.note_off[t.play_position]:
            #for note in self.note_off[t.pos[Modes.mTr.value]]:
            #del self.note_off[t.play_position][:] #clear the current midi output once it's been sent
            #del self.note_off[t.pos[Modes.mTr.value]][:] #clear the current midi output once it's been sent

            #for note in self.note_on[t.play_position]:
            for note in self.note_on[t.pos[Modes.mTr.value]]:
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,note.velocity)
            #    print("playing note", self.channel + note.channel_inc, note.pitch, " at: ",self.current_pos%32)
            del self.note_on[t.pos[Modes.mTr.value]][:] #clear the current midi output once it's been sent

        #end all notes that have expired
        i = 0
        finished_notes = list()
        new_duration_timers = [Note()]
        for note in self.duration_timers:
            note.decrement_duration()
            #print("decreasing duration for note:", note.pitch, "at: ", self.current_pos%32, "to: ", note.duration )
            if note.duration == 0:
                self.midi_out.send_noteon(self.channel + note.channel_inc, note.pitch,0)
            #    print("ending note", self.channel + note.channel_inc, note.pitch, " at: ", self.current_pos%32)
                finished_notes.append(i) # mark this note for removal from the timer list
            else:
                new_duration_timers.append(note)
            i = i + 1
        del self.duration_timers[:]
        self.duration_timers = new_duration_timers # set the duration timers list to the be non-zero items
        #for n in finished_notes:
        #    del self.duration_timers[n] #clear the timer once it's exhausted 


    @asyncio.coroutine
    def clock_out(self):
        yield from self.clock.sync(self.ticks)

    def draw(self):
        if self.frame_dirty:
            #print("drawing grid")
            buffer = monome.LedBuffer(self.width, self.height)

            if self.current_track.track_id == 0:
                buffer.led_level_set(0,7,15) #set the channel 1 indicator on
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator off
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch1[y][x] * 11 + highlight)
            elif self.current_track.track_id ==1:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,15)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch2[y][x] * 11 + highlight)
            elif self.current_track.track_id == 2:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,15)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,0)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch3[y][x] * 11 + highlight)
            elif self.current_track.track_id == 3:
                buffer.led_level_set(0,7,0)   #set the channel 1 indicator off
                buffer.led_level_set(1,7,0)  #set the channel 2 indicator on
                buffer.led_level_set(2,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(3,7,15)  #set the channel 4 indicator off
                #buffer.led_level_set(render_pos[0], render_pos[1], self.step_ch4[y][x] * 11 + highlight)
            if self.k_mode == Modes.mTr:
                buffer.led_level_set(5,7,15) #set the channel 1 indicator on
                buffer.led_level_set(6,7,0)  #set the channel 2 indicator off
                buffer.led_level_set(7,7,0)  #set the channel 3 indicator off
                buffer.led_level_set(8,7,0)  #set the channel 4 indicator off
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                # display triggers for each track
                for x in range(self.width):
                    for track in self.current_pattern.tracks:
                        buffer.led_level_set(x, 0+track.track_id, track.tr[x] * 15)
                        # display scale toggle
                        if x < 4:
                            buffer.led_level_set(track.track_id, 5, track.scale_toggle * 15)
                            #print("track: ", track.track_id, "x: ", x, "scale toggle: ", track.scale_toggle)
                            buffer.led_level_set(track.track_id, 6, (1-track.track_mute) * 15) #display is inverted - as if to turn tracks "off" rather than turn mutes "on"
            elif self.k_mode == Modes.mNote:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,15)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #show the triggers for that track on the top row
                    #buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    for y in range(1,self.height-1): #ignore bottom row
                        #render_pos = self.spanToGrid(x,y)
                        if self.current_track.track_id == 0:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch1[y][x] * 15 )
                        elif self.current_track.track_id == 1:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch2[y][x] * 15 )
                        elif self.current_track.track_id == 2:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch3[y][x] * 15 )
                        elif self.current_track.track_id == 3:
                            buffer.led_level_set(x, y, self.current_pattern.step_ch4[y][x] * 15 )
            elif self.k_mode == Modes.mOct:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,15)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #if self.current_channel == 1:
                    #fill a column bottom up in the x position
                    current_oct = self.current_track.octave[x]
                    if current_oct >= 0:
                        #print("start = ", 1, "end = ", 4-current_oct)
                        for i in range (4-current_oct,5):
                            buffer.led_level_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
                    if current_oct < 0:
                        for i in range (4,5-current_oct):
                            buffer.led_level_set(x, i, 15)
                            #print("current oct: ", current_oct, " drawing in row: ", i)
            elif self.k_mode == Modes.mDur:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,15)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #draw the accent toggles - this will move to a velocity page?
                    #if self.current_track.velocity[x]:
                    #    buffer.led_level_set(x, 0, 15)
                    #else:
                    #    buffer.led_level_set(x, 0, 0)
                    #if self.current_channel == 1:
                        #fill a column top down in the x position
                    for i in range (1,self.current_track.duration[x]+1): #ignore top row
                        buffer.led_level_set(x, i, 15)
                    for i in range (self.current_track.duration[x]+1,7): #ignore bottom row
                        buffer.led_level_set(x, i, 0)
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_level_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_level_set(x, i, 0)
            elif self.k_mode == Modes.mVel:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,15)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,0)
                for x in range(self.width):
                    #draw the accent toggles - this will move to a velocity page?
                    #if self.current_track.velocity[x]:
                    #    buffer.led_level_set(x, 0, 15)
                    #else:
                    #    buffer.led_level_set(x, 0, 0)
                    #if self.current_channel == 1:
                        #fill a column top down in the x position
                    for i in range (7-self.current_track.velocity[x],7): #ignore bottom row
                        buffer.led_level_set(x, i, 15)
                    for i in range (0,7-self.current_track.velocity[x]): #ignore top row
                        buffer.led_level_set(x, i, 0)
                    #show the triggers for that track on the top row
                    buffer.led_level_set(x, 0, self.current_track.tr[x] * 15)
                    #elif self.current_channel == 2:
                        #for i in range (1,self.current_pattern.tracks[1].duration[x]+1):
                        #    buffer.led_level_set(x, i, 15)
                        #for i in range (self.current_pattern.tracks[1].duration[x]+1,7):
                        #    buffer.led_level_set(x, i, 0)
            elif self.k_mode == Modes.mScale:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,15)
                buffer.led_level_set(15,7,0)
                buffer.led_level_set(15,7,0)
                #clear any previous scale
                for ix in range (15):
                    for iy in range (1,7):
                        buffer.led_level_set(ix,iy, 0)
                # show the selected scale 
                buffer.led_level_set(self.cur_scale_id//6,7-self.cur_scale_id%6-1, 15)
                # set a transpose reference point
                buffer.led_level_set(7,7,15)
                #display the actual scale
                for sd in range (1,8):
                    buffer.led_level_set(7+self.cur_trans+self.current_preset.scale_data[self.cur_scale_id][sd],7-sd, 15)
                    #print("sd: ", sd, "scale val: ", self.scale_data[self.cur_scale_id][sd], "pos: ", 4+self.scale_data[self.cur_scale_id][sd],7-sd-1)
            elif self.k_mode == Modes.mPattern:
                buffer.led_level_set(5,7,0)
                buffer.led_level_set(6,7,0)
                buffer.led_level_set(7,7,0)
                buffer.led_level_set(8,7,0)
                buffer.led_level_set(9,7,0)
                buffer.led_level_set(14,7,0)
                buffer.led_level_set(15,7,15)
                for i in range(16):
                    buffer.led_level_set(i,0,0)
                buffer.led_level_set(self.current_pattern.pattern_id,0,15)
            if self.k_mod_mode == ModModes.modLoop:
                buffer.led_level_set(10,7,15)
                buffer.led_level_set(11,7,0)
                buffer.led_level_set(12,7,0)
            elif self.k_mod_mode == ModModes.modTime:
                buffer.led_level_set(10,7,0)
                buffer.led_level_set(11,7,15)
                buffer.led_level_set(12,7,0)
            elif self.k_mod_mode == ModModes.modProb:
                buffer.led_level_set(10,7,0)
                buffer.led_level_set(11,7,0)
                buffer.led_level_set(12,7,15)

            # draw trigger bar and on-states
    #        for x in range(self.width):
    #            buffer.led_level_set(x, 6, 4)

    #        for y in range(6):
    #            if self.step_ch1[y][self.play_position] == 1:
    #                buffer.led_level_set(self.play_position, 6, 15)

            # draw play position
            #current_pos = yield from self.clock.sync()
            #print("runcible:",(self.current_pos//self.ticks)%16)
            #render_pos = self.spanToGrid(self.play_position, 0)
            #if ((self.current_pos//self.ticks)%16) < 16:
    #           print("Pos",self.play_position)
            #    buffer.led_level_set(render_pos[0], render_pos[1], 15)
            #else:
            #    buffer.led_level_set(render_pos[0], render_pos[1], 0) # change this to restore the original state of the led

            # display the other track positions
            # I think this could all be simplified
            # change the bounds of the first if condition to match the
            # loop start and end points
            if self.k_mode == Modes.mTr:
                previous_step = [0,0,0,0]
                for track in self.current_pattern.tracks:
                    #track 1
                    if track.pos[Modes.mTr.value] >= track.lstart[Modes.mTr.value] and track.pos[Modes.mTr.value] <= track.lend[Modes.mTr.value]:
                    #if ((self.current_pos//self.ticks)%16) < 16:
                        if buffer.levels[0+track.track_id][track.pos[Modes.mTr.value]] == 0:
                            buffer.led_level_set(track.pos[Modes.mTr.value]-1, 0+track.track_id, previous_step[track.track_id])
                            buffer.led_level_set(track.pos[Modes.mTr.value], 0+track.track_id, 15)
                            previous_step[track.track_id] = 0
                        else: #toggle an already lit led as we pass over it
                            previous_step[track.track_id] = 15
                            buffer.led_level_set(track.pos[Modes.mTr.value], 0+track.track_id, 0)
                            #buffer.led_level_set(track.play_position, 0+track.track_id, 15)
                    else:
                        buffer.led_level_set(self.current_track.pos[Modes.mTr.value], 0, 0)

                #if ((self.current_pos//self.ticks)%16) < 16:
                #    buffer.led_level_set(track.play_position, 0+track.track_id, 15)
                #else:
                #    buffer.led_level_set(self.current_track.play_position, 0, 0)
                ##track 2
                #if ((self.current_pos//self.ticks)%16) < 16:
                #    buffer.led_level_set(self.current_track.play_position, 1, 15)
                #else:
                #    buffer.led_level_set(self.current_track.play_position, 1, 0)
                ##track 3
                #if ((self.current_pos//self.ticks)%16) < 16:
                #    buffer.led_level_set(self.current_track.play_position, 2, 15)
                #else:
                #    buffer.led_level_set(self.current_track.play_position, 2, 0)
                #track 4
                #if ((self.current_pos//self.ticks)%16) < 16:
                #    buffer.led_level_set(self.current_track.play_position, 3, 15)
                #else:
                #    buffer.led_level_set(self.current_track.play_position, 3, 0)
            else:
                if self.k_mode.value < Modes.mScale.value : # all other modes except scale or pattern
                    #display play position of current track
                    #if ((self.current_pos//self.ticks)%16) >= self.loop_start and ((self.current_pos//self.ticks)%16) <= self.loop_end:
                    previous_step = [0,0,0,0]
                    # change to use the paramter track position and parameter lstart and lend
                    #if self.current_track.play_position >= self.current_track.loop_start and self.current_track.play_position <= self.current_track.loop_end:
                    if buffer.levels[0+self.current_track.track_id][self.current_track.pos[self.k_mode.value]] == 0:
                        buffer.led_level_set(self.current_track.pos[self.k_mode.value]-1, 0, previous_step[self.current_track.track_id])
                        buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 15)
                        previous_step[self.current_track.track_id] = 0
                    else: #toggle an already lit led as we pass over it
                        previous_step[self.current_track.track_id] = 15
                        buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 0)
                    #buffer.led_level_set(self.current_track.play_position, 0, 15)
                #else:
                #    buffer.led_level_set(self.current_track.pos[self.k_mode.value], 0, 0)

            # update grid
            buffer.render(self)
            self.frame_dirty = False 

    def grid_key(self, addr, path, *args):
        x, y, s = self.translate_key(addr,path, *args)
        #self.led_set(x, y, s)
        if s ==1 and y == 0:
            if x == 0:
                #print("Selected Track 1")
                self.current_track = self.current_pattern.tracks[0]
                self.current_track_id = self.current_pattern.tracks[0].track_id
                # track a ctrl key hold here
                self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
                print("ctr_keys_held: ", self.ctrl_keys_held)
                if self.ctrl_keys_held == 1:
                    self.ctrl_keys_last.append(x)
                    print("ctr_keys_last: ", self.ctrl_keys_last)
            elif x == 1:
                #print("Selected Track 2")
                self.current_track = self.current_pattern.tracks[1]
                self.current_track_id = self.current_pattern.tracks[1].track_id
            elif x == 2:
                #print("Selected Track 3")
                self.current_track = self.current_pattern.tracks[2]
                self.current_track_id = self.current_pattern.tracks[2].track_id

                # track a ctrl key hold here
                self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
                print("ctr_keys_held: ", self.ctrl_keys_held)
                if self.ctrl_keys_held == 2:
                    self.ctrl_keys_last.append(x)
                    print("ctr_keys_last: ", self.ctrl_keys_last)
            elif x == 3:
                #print("Selected Track 4")
                self.current_track = self.current_pattern.tracks[3]
                self.current_track_id = self.current_pattern.tracks[3].track_id
            elif x == 5:
                self.k_mode = Modes.mTr
                #print("Selected:", self.k_mode)
            elif x == 6:
                self.k_mode = Modes.mNote
                #print("Selected:", self.k_mode)
            elif x == 7:
                self.k_mode = Modes.mOct
                #print("Selected:", self.k_mode)
            elif x == 8:
                self.k_mode = Modes.mDur
                #print("Selected:", self.k_mode)
            elif x == 9:
                self.k_mode = Modes.mVel
                #print("Selected:", self.k_mode)
            elif x == 10:
                self.k_mod_mode = ModModes.modLoop
                #print("Selected:", self.k_mod_mode)
            elif x == 11:
                self.k_mod_mode = ModModes.modTime
                #print("Selected:", self.k_mod_mode)
            elif x == 12:
                self.k_mod_mode = ModModes.modProb
                #print("Selected:", self.k_mod_mode)
            elif x == 14:
                self.k_mode = Modes.mScale
                #print("Selected:", self.k_mode)
            elif x == 15:
                self.k_mode = Modes.mPattern
                #print("Selected:", self.k_mode)

                # track a ctrl key hold here
                self.ctrl_keys_held = self.ctrl_keys_held + (s * 2) - 1
                print("ctr_keys_held: ", self.ctrl_keys_held)
                if self.ctrl_keys_held == 3:
                    self.ctrl_keys_last.append(x)
                    print("ctr_keys_last: ", self.ctrl_keys_last)
                    self.ctrl_keys_held = 0
                    if self.ctrl_keys_last == [0,2,15]:
                        del self.ctrl_keys_last[:]
                        self.disconnect()
                    else:
                        del self.ctrl_keys_last[:]
        elif s == 0 and y == 0 and (x == 10 or x == 11 or x == 12):
                self.k_mod_mode = ModModes.modNone
        elif s == 0 and y == 0:
            self.ctrl_keys_held = 0
            del self.ctrl_keys_last[:]
        elif s == 1 and y > 0:
            if y == 7:
                if self.k_mode == Modes.mTr:
                    if self.k_mod_mode == ModModes.modTime:
                        self.current_track.tmul[Modes.mTr.value] = x
                        self.current_track.tmul[Modes.mNote.value] = x # for now all time multipliers are set at once
                        self.current_track.tmul[Modes.mOct.value] = x
                        self.current_track.tmul[Modes.mDur.value] = x
                        self.current_track.tmul[Modes.mVel.value] = x
                        print("tmul: ", self.current_track.tmul[Modes.mTr.value])
            if y < 7:
                #set scale mode toggles
                if self.k_mode == Modes.mTr:
                    #print("Trigger page key:", x, y)
                    if y == 2 and x < 4:
                        self.current_pattern.tracks[x].scale_toggle ^= 1
                        #print ("toggling scale for track: ", x)
                    if y == 1 and x < 4:
                        self.current_pattern.tracks[x].track_mute ^= 1
                        #print ("toggling mute for track: ", x)
                # Note entry
                if self.k_mode == Modes.mNote:
                    if self.current_track.track_id == 0:
                        self.current_pattern.step_ch1[7-y][x] ^= 1
                    elif self.current_track.track_id == 1:
                        self.current_pattern.step_ch2[7-y][x] ^= 1
                    elif self.current_track.track_id == 2:
                        self.current_pattern.step_ch3[7-y][x] ^= 1
                    else:
                        self.current_pattern.step_ch4[7-y][x] ^= 1
                    if y not in self.current_track.note[x]:
                        self.current_track.note[x].append(y)
                        #print("append: ", y, "at ", x)
                    else:
                        self.current_track.note[x].remove(y)
                        #print("remove: ", y, "at ", x)
                    if self.current_track.duration[x] == 0:
                        self.current_track.duration[x] = 1
                    # toggle the trigger if there are no notes
                    if len(self.current_track.note[x]) > 0:
                        self.current_track.tr[x] = 1
                        #print("note len: ", self.current_track.note[x])
                    else:
                        self.current_track.tr[x] = 0
                        #print("note len: ", self.current_track.note[x])

                    #if self.current_track.tr[x] == 0:
                    #    self.current_track.duration[x] = 0 # change this when param_sync is off
                    #else:
                    #    self.step_ch2[7-y][x] ^= 1
                    #    self.current_pattern.tracks[1].note[x] = y
                    #    self.current_pattern.tracks[1].duration[x] = 1
                    #    self.current_pattern.tracks[1].tr[x] ^= 1
                    #self.draw()
                    self.frame_dirty = True 
                # octave entry
                if self.k_mode == Modes.mOct: 
                    #if self.current_channel == 1:
                    if y < 7 and y > 0:
                        self.current_track.octave[x] = y-3
                        #print("grid_key = ", y, "octave = ", self.current_pattern.tracks[0].octave[x])
                    #else:
                    #    if y < 6 and y > 0:
                    #        self.current_pattern.tracks[1].octave[x] = y-3
                    #self.draw()
                    self.frame_dirty = True 
                # duration entry
                if self.k_mode == Modes.mDur:
                    # add loop setting code based on loop mod
                    # add time setting code based on time mod
                    # add probability setting based on prob mod - default to standard duration if prob comes up "false"?
                    self.current_track.duration[x] = 7-y
                    self.frame_dirty = True 
                if self.k_mode == Modes.mVel:
                    # add loop setting code based on loop mod
                    # add time setting code based on time mod
                    # add probability setting based on prob mod - default to standard velocity if prob comes up "false"?
                    self.current_track.velocity[x] = y
                    #print("entered velocity: ", self.current_track.velocity[x])
                    self.frame_dirty = True 
                if self.k_mode == Modes.mScale:
                    if x < 3:
                        if y < 7 and y > 0:
                            self.cur_scale_id = y-1+x*6
                            self.calc_scale(self.cur_scale_id)
                            #print("selected scale: ", self.cur_scale_id)
                    else:
                        # transpose the scale up or down by semitones from the mid point (col 7)
                        self.cur_trans = x-7
                        self.calc_scale(self.cur_scale_id)
                    self.frame_dirty = True 
                # preset entry
                if self.k_mode == Modes.mPattern:
                    if x < 3:
                        if y < 6 and y > 0:
                            self.state.current_preset_id = y-1+x*5
                            self.current_preset = self.state.presets[self.state.current_preset_id]
                            #print("selected preset: ", self.state.current_preset_id)
                    #self.draw()
                    self.frame_dirty = True 
            elif self.k_mode == Modes.mPattern and y == 7:
                self.current_preset.current_pattern = x
                self.current_pattern = self.current_preset.patterns[self.current_preset.current_pattern]
                self.current_track = self.current_pattern.tracks[self.current_track_id]
               # print("selected pattern: ", self.current_preset.current_pattern)
            elif y == 7: #switch to require modLoop? - shift to be inside each parameter
                self.keys_held = self.keys_held + (s * 2) - 1
                #print("keys_held: ", self.keys_held)
                # cut
                if s == 1 and self.keys_held == 1 and self.k_mod_mode == ModModes.modLoop:
                    self.cutting = True
                    #self.current_track.next_position = x #change to be per parameter next
                    #self.current_track.loop_last = x #change to be per parameter last
                    self.current_track.next_pos[self.k_mode.value]= x #change to be per parameter next
                    self.current_track.last_pos[self.k_mode.value] = x
                    print("track_last: ", self.current_track.last_pos[self.k_mode.value])
                # set loop points
                elif s == 1 and self.keys_held == 2:
                    if self.current_track.last_pos[self.k_mode.value] < x: # don't wrap around, for now
                        #self.current_track.loop_start = self.current_track.loop_last #change to per parameter lstart
                        self.current_track.lstart[self.k_mode.value] = self.current_track.last_pos[self.k_mode.value]#change to per parameter lstart
                        print("track_lstart: ", self.current_track.lstart[self.k_mode.value])
                        #self.current_track.loop_end = x #change to per parameter lend: self.current_track.lend[self.k_mode.value] = x
                        self.current_track.lend[self.k_mode.value] = x #change to per parameter lend: self.current_track.lend[self.k_mode.value] = x
                        print("key_lend: ", self.current_track.lend[self.k_mode.value])
                        self.keys_held = 0
                    else:
                        self.keys_held = 0
                    #print("loop start: ", self.loop_start[self.current_track], "end: ", self.loop_end[self.current_track])

    def restore_state(self):
        #load the pickled AST for this feature
        self.state = pickle.load(open(self.pickle_file_path, "rb"))

    def save_state(self):
        with open(self.pickle_file_path, 'wb') as pickle_handle:
            pickle.dump(self.state, pickle_handle)



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

    #pygame.init()
    #pygame.midi.init()
    #device_count = pygame.midi.get_count()
    #print (pygame.midi.get_default_output_id())
    #midiport = 0
    #clock_out = 3
    #info = list()
    #for i in range(device_count):
    #   info = pygame.midi.get_device_info(i)
    #   print (str(i) + ": " + str(info[1]) + " " + str(info[2]) + " " + str(info[3]))
    #   if 'MIDI 6' in str(info[1]) and info[3] == 1:
    #       midiport = i
       #if 'MIDI 1' in str(info[1]) and info[3] == 0:
       #   clock_out = i

    #midi_out = pygame.midi.Output(midiport, 0)

    clock_out = 3
    print("Available ports:",rtmidi2.get_out_ports())
    midiport = rtmidi2.MidiOut().ports_matching("iConnectMIDI4+ 20:5")
    midi_out = rtmidi2.MidiOut()
    if midiport:
        midi_out.open_port(midiport[0])
        print ("using output_id : %s " % midi_out.get_port_name(midiport[0]))
    else:
        print ("Port not found")
    print ("using clock source: %s " % clock_out)
    channel_out = 2
    #page = 1
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
          'runcible': g1,
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
        midi_out.close_port()
        print('kthxbye')

