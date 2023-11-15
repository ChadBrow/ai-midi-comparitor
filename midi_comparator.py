import time as ti
from apscheduler.schedulers.blocking import BlockingScheduler
from concurrent.futures import ThreadPoolExecutor
from mido import open_input
from pygame import mixer, midi
from pyfluidsynth_rip.fluidsynth import Synth

from util import Note


# class GameClock(threading.Thread):
#     def __init__(self, comparator):
#         self.comparator = comparator
#         self.stopped = threading.Event()
#         self.tickClock = 0
#         self.timeClock = 0
#         self.tickTime = self.comparator.tickTime
    
#     def stop(self):
#         self.stopped.set()
    
#     def run(self):
#         print("Running")
#         self.startTime = time.time()
#         print(self.startTime)
#         while not self.stopped.wait(self.tickTime):
#             self.tickClock += 1
#             self.comparator.tick(self.tickClock)

class MidiComparator:
    def __init__(self, score, scoreInfo, keepMetronomeOn=False, pianoFont="grand_piano.sf2"):
        self.time = 0
        self.score = score
        self.info = scoreInfo
        self.keepMetronomeOn = keepMetronomeOn

        self.metronomeOn = True
        self.tickTime = scoreInfo.tempo / (480 * 1000000) #will likely need to slow this down
        self.tickClock = 0

        self.running = False

        self.port = open_input()

        self.maxTickDif = 480 #for our comparison func we will only consider notes within one beat
        self.pressedNotes = {}
        self.missedNotes = []
        self.hitNotes = []

        mixer.init()
        mixer.music.load("metronome.mp3")
        # midi.init()
        # self.piano = midi.Output(0)
        # self.piano.set_instrument(0)
        # self.paino.set_soundfont("soundfonts/grand_piano.sf2")

        #start up our synths
        #lib = "/opt/homebrew/opt/fluid-synth/lib/libfluidsynth.dylib"
        # fs = Synth()
        self.piano = Synth(gain=1.0)
        # self.metronome = fluidsynth.Synth()
        self.piano.start()
        # self.metronome.start()

        pianoFont = self.piano.sfload("soundfonts/" + pianoFont)
        # pianoFont = self.piano.sfload("pyFluidSynth_rip/example.sf2")
        # # metronomeFont = self.metronome.sfload("soundfonts/metronome.sf2")
        self.piano.program_select(0, pianoFont, 0, 0)

    
    def stop(self):
        if not self.running:
            return
        print("Stopping")
        self.running = False

        #remove scheduled job
        self.sched.remove_job('clock')
        self.sched.shutdown()
        del self.sched

        #delete our synths
        self.piano.delete()
        # self.metronome.delete()

        #add all remaining notes to missed notes
        self.missedNotes += self.score

        self.postGameAnalysis()

        # del self.midiPlayer
        # midi.quit()
    
    def run(self):
        #here we run the game
        if self.running:
            return
        
        #metronome count in
        self.countIn()

        #threading because we are going to be doing a lot very quickly
        self.running = True
        with ThreadPoolExecutor() as executor:
            #we use blocking scheduler to make sure that we run tick at the exact same increment no matter how long it takes
            self.sched = BlockingScheduler({'apscheduler.job_defaults.max_instances': 4})
            self.sched.add_job(self.tick, "interval", seconds=self.tickTime, id='clock')
            try:
                self.sched.start()
                # while True:
                #     for msg in self.port.iter_pending():
                #         self.processMessage(msg, self.tickClock) 
            except KeyboardInterrupt: #accept ^C as exit
                print("Finishing---------.")
            finally:
                # clock.stop()
                self.stop()
    
    def printEvent(event):
        print(event.__dict__)
    
    def tick(self):
        if self.metronomeOn:
            pass
        if self.tickClock > self.info.length * 200:
            self.stop()
        if self.tickClock % 480 == 0:
            mixer.music.play()
        # print("Tick---------")
        # print(time.time())s
        # print(self.tickClock)
        for msg in self.port.iter_pending():
            self.processMessage(msg, self.tickClock)

        self.tickClock += 1

    def processMessage(self, msg, time):
        #only accept note on and off messages
        if msg.type == "note_on" or msg.type == "note_off":
            if msg.velocity == 0:
                #this is a note off message
                self.piano.noteoff(0, msg.note)
                #start by playing the note
                # self.midiPlayer.note_off(msg.note, msg.velocity)
                if msg.note not in self.pressedNotes:
                    #note was released without being pressed. Should never happend
                    return
                #note has been finished. Let's compare it to the score
                note = self.pressedNotes[msg.note]
                note.end = time
                del self.pressedNotes[msg.note] #this note is no longer pressed
                match = self.compare(note)
                #if we get a match then great
                if match:
                    print(match)
                    self.hitNotes.append(match)
                return
            
            #this is a note on message
            print(msg.note, msg.velocity)
            self.piano.noteon(0, msg.note, msg.velocity)
            #start by playing the note
            # self.midiPlayer.note_on(msg.note, msg.velocity)
            self.pressedNotes[msg.note] = Note(msg.note, time, -1, msg.velocity)

    def compare(self, note):
        curBest = None #will contain tuple of (note played, score note, time played - time score, time released dif)
        indexBest = -1
        i = 0

        while i < len(self.score): #use while loop cause we'll be doing some popping
            if self.score[i].start > note.start + self.maxTickDif:
                #we have left the range of acceptable notes
                break
            if self.score[i].start < note.start - self.maxTickDif:
                #this element in score is old enough to be considered a missed note
                self.missedNotes.append(self.score.pop(i))
                i += 1
                continue
            if self.score[i].val != note.val:
                #for now we will assume that the player never hits a wrong note
                #so we will not compare score notes with different vaues from the current note
                #This is NOT a good assumption to make, but we can easily fix this later. Consider this WIP
                i += 1
                continue
            startDif = note.start - self.score[i].start
            if indexBest == -1 or abs(startDif) < abs(curBest[2]):
                #if there is not already a current best match or this new note is a better match
                curBest = (note, self.score[i], startDif, note.end - self.score[i].end)
                indexBest = i
                #if this is a new best match and timeDif > 0 then all subsequent notes in the score that match this note
                #must be worse notes because score is sorted by order of notes so timeDif only goes up. So we can break
                if startDif > 0:
                    break
            i += 1
        
        #pop the note we matched from the score. So long as the maxTickDif isn't too great then this should be alright
        if indexBest > -1:
            self.score.pop(indexBest)

        return curBest
    
    def postGameAnalysis(self):
        print("Game Over")
        print("Number of notes hit:", len(self.hitNotes))
        print("Number of notes missed:", len(self.missedNotes))
    
    def countIn(self):
        for i in range(2 * self.info.timeSigNum):
            mixer.music.play()
            ti.sleep(self.info.tempo / 1000000)