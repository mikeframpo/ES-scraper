#!/usr/bin/env python
import os, imghdr, urllib, urllib2, sys, argparse, zlib, unicodedata, re
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, SubElement
from PIL import Image

import abc
import historydat_parser as hp
from urlparse import urlparse

parser = argparse.ArgumentParser(description='ES-scraper, a scraper for EmulationStation')
parser.add_argument("-w", metavar="value", help="defines a maximum width (in pixels) for boxarts (anything above that will be resized to that value)", type=int)
parser.add_argument("-noimg", help="disables boxart downloading", action='store_true')
parser.add_argument("-v", help="verbose output", action='store_true')
parser.add_argument("-f", help="force re-scraping (ignores and overwrites the current gamelist)", action='store_true')
parser.add_argument("-crc", help="CRC scraping", action='store_true')
parser.add_argument("-p", help="partial scraping (per console)", action='store_true')
parser.add_argument("-m", help="manual mode (choose from multiple results)", action='store_true')
parser.add_argument('-newpath', help="gamelist & boxart are written in $HOME/.emulationstation/%%NAME%%/", action='store_true')
parser.add_argument('-hisdat', help='For arcade (MAME) games, game info will be fetched from the mame history.dat file in the roms directory', action='store_true')
parser.add_argument('-fix', help="temporary thegamesdb missing platform fix", action='store_true')
args = parser.parse_args()

def normalize(s):
   return ''.join((c for c in unicodedata.normalize('NFKD', unicode(s)) if unicodedata.category(c) != 'Mn'))

def fixExtension(file):    
    newfile="%s.%s" % (os.path.splitext(file)[0],imghdr.what(file))
    os.rename(file, newfile)
    return newfile

def readConfig(file):
    lines=config.read().splitlines()
    systems=[]
    for line in lines:
        if not line.strip() or line[0]=='#':
            continue
        else:
            if "NAME=" in line:
                name=line.split('=')[1]
            if "PATH=" in line:
                path=line.split('=')[1]
            elif "EXTENSION" in line:
                ext=line.split('=')[1]
            elif "PLATFORMID" in line:
                pid=line.split('=')[1]
                if not pid:
                    continue
                else:
                    system=(name,path,ext,pid)
                    systems.append(system)
    config.close()
    return systems

def crc(fileName):
    prev = 0
    for eachLine in open(fileName,"rb"):
        prev = zlib.crc32(eachLine, prev)
    return "%X"%(prev & 0xFFFFFFFF)

def indent(elem, level=0):
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def getPlatformName(id):
    url = "http://thegamesdb.net/api/GetPlatform.php"
    req = urllib2.Request(url, urllib.urlencode({'id':id}), headers={'User-Agent' : "RetroPie Scraper Browser"})
    data = urllib2.urlopen( req )
    platform_data = ET.parse(data)
    return platform_data.find('Platform/Platform').text

def exportList(gamelist):
    if gamelistExists and args.f is False:
        for game in gamelist.iter("game"):
            existinglist.getroot().append(game)

        indent(existinglist.getroot())
        ET.ElementTree(existinglist.getroot()).write("gamelist.xml")
        print "Done! %s updated." % os.getcwd()+"/gamelist.xml"
    else:
        indent(gamelist)
        ET.ElementTree(gamelist).write("gamelist.xml")
        print "Done! List saved on %s" % os.getcwd()+"/gamelist.xml"

def getFiles(base):
    dict=set([])
    for files in sorted(os.listdir(base)):
        if files.endswith(tuple(ES_systems[var][2].split(' '))):
            filepath=os.path.abspath(os.path.join(base, files))
            dict.add(filepath)
    return dict

class InfoFetcher(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def gameFound(self):
        pass

    @abc.abstractmethod
    def getTitle(self):
        pass

    @abc.abstractmethod
    def getDescription(self):
        pass

    @abc.abstractmethod
    def getMarquee(self):
        pass

    @abc.abstractmethod
    def getSnapshot(self):
        pass

    @abc.abstractmethod
    def getRelDate(self):
        pass

    @abc.abstractmethod
    def getPublisher(self):
        pass

    @abc.abstractmethod
    def getDeveloper(self):
        pass

    @abc.abstractmethod
    def getGenres(self):
        pass

class HistoryDatFetcher(InfoFetcher):

    hp_parser = None

    def __init__(self, filepath, romdir):
        if HistoryDatFetcher.hp_parser is None:
            histdat_file = os.path.join(romdir, 'history.dat')
            HistoryDatFetcher.hp_parser = hp.HistDatParser(histdat_file)
        self.romname = os.path.splitext(os.path.basename(filepath))[0]
        self.game = HistoryDatFetcher.hp_parser.get_game('info', self.romname)
    
    def gameFound(self):
        return self.game is not None

    def getTitle(self):
        return self.game.name

    def getDescription(self):
        return None

    def getMarquee(self):
        return 'http://mamedb.com/marquees/' + self.romname + '.png'

    def getSnapshot(self):
        return 'http://mamedb.com/snap/' + self.romname + '.png'

    def getRelDate(self):
        return self.game.year

    def getPublisher(self):
        return self.game.publisher

    def getDeveloper(self):
        return None

    def getGenres(self):
        return None

class GamesDBInfoFetcher(InfoFetcher):

    def __init__(self, file, platformId):
        self.data = getGameInfo(file, platformId)

    def gameFound(self):
        return self.data is not None

    def getTitle(self):
        return getTitle(self.data)

    def getDescription(self):
        return getDescription(self.data)

    def getMarquee(self):
        return None

    def getSnapshot(self):
        return None

    def getRelDate(self):
        return getPublisher(self.data)

    def getPublisher(self):
        return getPublisher(self.data)

    def getDeveloper(self):
        return getDeveloper(self.data)

    def getGenres(self):
        return getGenres(self.data)

def getGameInfo(file,platformID):
    title=re.sub(r'\[.*?\]|\(.*?\)', '', os.path.splitext(os.path.basename(file))[0]).strip()
    if args.crc:
        crcvalue=crc(file)
        if args.v:
            try:
                print "CRC for %s: %s" % (os.path.basename(file), crcvalue)
            except zlib.error as e:
                print e.strerror
        URL = "http://api.archive.vg/2.0/Game.getInfoByCRC/xml/7TTRM4MNTIKR2NNAGASURHJOZJ3QXQC5/%s" % crcvalue
        values={}
    else:
        URL = "http://thegamesdb.net/api/GetGame.php"
        platform = getPlatformName(platformID)
        if platform == "Arcade": title = getRealArcadeTitle(title)            
        
        if args.fix:
            try:                
                fixreq = urllib2.Request("http://thegamesdb.net/api/GetGamesList.php", urllib.urlencode({'name' : title, 'platform' : platform}), headers={'User-Agent' : "RetroPie Scraper Browser"})
                fixdata=ET.parse(urllib2.urlopen(fixreq)).getroot()
                if fixdata.find("Game") is not None:            
                    values={ 'id': fixdata.findall("Game/id")[chooseResult(fixdata)].text if args.m else fixdata.find("Game/id").text }
            except:
                return None
        else:
            values={'name':title,'platform':platform}

    try:
        req = urllib2.Request(URL,urllib.urlencode(values), headers={'User-Agent' : "RetroPie Scraper Browser"})
        remotedata = urllib2.urlopen( req )
        data=ET.parse(remotedata).getroot()
    except ET.ParseError:
        print "Malformed XML found, skipping game.. (source: {%s})" % URL
        return None

    try:
        if args.crc:
            result = data.find("games/game")
            if result is not None and result.find("title").text is not None:
                return result
        elif data.find("Game") is not None:
            return data.findall("Game")[chooseResult(data)] if args.m else data.find("Game")
        else:
            return None
    except Exception, err:
        print "Skipping game..(%s)" % str(err)
        return None

def getText(node):
    return normalize(node.text) if node is not None else None

def getTitle(nodes):
    if args.crc:
        return getText(nodes.find("title"))
    else:
        return getText(nodes.find("GameTitle"))

def getGamePlatform(nodes):
    if args.crc:
        return getText(nodes.find("system_title"))
    else:
        return getText(nodes.find("Platform"))

def getRealArcadeTitle(title):
    print "Fetching real title for %s from mamedb.com" % title
    URL  = "http://www.mamedb.com/game/%s" % title
    data = "".join(urllib2.urlopen(URL).readlines())
    m    = re.search('<b>Name:.*</b>(.+) .*<br/><b>Year', data)
    if m:
       print "Found real title %s for %s on mamedb.com" % (m.group(1), title)
       return m.group(1)
    else:
       print "No title found for %s on mamedb.com" % title
       return title

def getDescription(nodes):
    if args.crc:
        return getText(nodes.find("description"))
    else:
        return getText(nodes.find("Overview"))

def getImage(nodes):
    if args.crc:
        return getText(nodes.find("box_front"))
    else:
        return getText(nodes.find("Images/boxart[@side='front']"))

def getTGDBImgBase(nodes):
    return nodes.find("baseImgUrl").text

def getRelDate(nodes):
    if args.crc:
        return None
    else:
        return getText(nodes.find("ReleaseDate"))

def getPublisher(nodes):
    if args.crc:
        return None
    else:
        return getText(nodes.find("Publisher"))

def getDeveloper(nodes):
    if args.crc:
        return getText(nodes.find("developer"))
    else:
        return getText(nodes.find("Developer"))

def getGenres(nodes):
    genres=[]
    if args.crc and nodes.find("genre") is not None:
        for item in getText(nodes.find("genre")).split('>'):
            genres.append(item)
    elif nodes.find("Genres") is not None:
        for item in nodes.find("Genres").iter("genre"):
            genres.append(item.text)

    return genres if len(genres)>0 else None

def resizeImage(img,output):
    maxWidth= args.w
    if (img.size[0]>maxWidth):
        print "Boxart over %spx. Resizing boxart.." % maxWidth
        height = int((float(img.size[1])*float(maxWidth/float(img.size[0]))))
        img.resize((maxWidth,height), Image.ANTIALIAS).save(output)

def downloadBoxart(path,output):
    return os.system("wget -q %s --output-document=\"%s\"" % (path,output))

def skipGame(list, filepath):
    for game in list.iter("game"):
        if game.findtext("path")==filepath:
            if args.v:
                print "Game \"%s\" already in gamelist. Skipping.." % os.path.basename(filepath)
            return True

def chooseResult(nodes):
    results=nodes.findall('Game')
    if len(results) > 1:
        for i,v in enumerate(results):
            try:
                print "[%s] %s | %s" % (i,getTitle(v), getGamePlatform(v))
            except Exception as e:
                print "Exception! %s %s %s" % (e, getTitle(v), getGamePlatform(v))

        return int(raw_input("Select a result (or press Enter to skip): "))
    else:
        return 0

def fetchImage(url, image, dest_folder, img_id):

    print "Downloading boxart.."

    if not os.path.isdir(dest_folder):
        os.mkdir(dest_folder)

    url_parsed = urlparse(url)
    dest_filename = os.path.basename(url_parsed.path)
    dest_path = os.path.join(dest_folder, dest_filename)

    rc = downloadBoxart(url, dest_path)
    if rc != 0:
        raise Exception('Image fetch failed from url: ' + url)

    if not os.path.exists(dest_path):
        raise Exception(
            'Image fetched successfully but failed to write to dest directory.')

    dest_path = fixExtension(dest_path)
    image.text = dest_path
    image.attrib['id'] = img_id

    if args.w:
        try:
            resizeImage(Image.open(dest_path), dest_path)
        except:
            print "Image resize error"

def scanFiles(SystemInfo):
    name=SystemInfo[0]
    folderRoms=SystemInfo[1]
    extension=SystemInfo[2]
    platformID=SystemInfo[3]

    global gamelistExists
    global existinglist
    gamelistExists = False

    gamelist = Element('gameList')
    folderRoms = os.path.expanduser(folderRoms)

    if args.newpath is False:
        destinationFolder = folderRoms;
    else:
        destinationFolder = os.environ['HOME']+"/.emulationstation/%s/" % name

    try:
        os.chdir(destinationFolder)
    except OSError as e:
        print "%s : %s" % (destinationFolder, e.strerror)
        return

    print "Scanning folder..(%s)" % folderRoms

    if os.path.exists("gamelist.xml"):
        try:
            existinglist=ET.parse("gamelist.xml")
            gamelistExists=True
            if args.v:
                print "Gamelist already exists: %s" % os.path.abspath("gamelist.xml")
        except:
            gamelistExists=False
            print "There was an error parsing the list or file is empty"

    for root, dirs, allfiles in os.walk(folderRoms, followlinks=True):
        allfiles.sort()
        try:
            for files in allfiles:
                if files.endswith(tuple(extension.split(' '))):
                    filepath=os.path.abspath(os.path.join(root, files))
                    filename = os.path.splitext(files)[0]

                    if gamelistExists and not args.f:
                        if skipGame(existinglist,filepath):
                            continue

                    print "Trying to identify %s.." % files

                    if args.hisdat:
                        fetcher = HistoryDatFetcher(filepath, folderRoms)
                    else:
                        fetcher = GamesDBInfoFetcher(filepath, platformID)
 
                    if not fetcher.gameFound():
                        print 'No info found for {0}'.format(filepath)
                        continue

                    str_title=fetcher.getTitle()

                    #TODO:re-enable me once the description is nicely shortened
                    #str_des=fetcher.getDescription()
                    str_des=''

                    str_marquee_url = fetcher.getMarquee()
                    str_snap_url = fetcher.getSnapshot()

                    str_rd=fetcher.getRelDate()
                    str_pub=fetcher.getPublisher()
                    str_dev=fetcher.getDeveloper()
                    lst_genres=fetcher.getGenres()

                    if str_title is not None:
                        game = SubElement(gamelist, 'game')
                        path = SubElement(game, 'path')
                        name = SubElement(game, 'name')
                        desc = SubElement(game, 'desc')

                        if str_marquee_url is not None:
                            img_marquee = SubElement(game, 'image')
                        if str_snap_url is not None:
                            img_snap = SubElement(game, 'image')

                        releasedate = SubElement(game, 'releasedate')
                        publisher=SubElement(game, 'publisher')
                        developer=SubElement(game, 'developer')
                        genres=SubElement(game, 'genres')

                        path.text=filepath
                        name.text=str_title
                        print "Game Found: %s" % str_title

                    if str_des is not None:
                        desc.text=str_des
    
                    if args.newpath is True:
                        imgroot="./"
                    else:
                        imgroot=os.path.abspath(root)

                    if args.noimg is False:
                        fetchImage(str_marquee_url, img_marquee,
                                    os.path.join(imgroot, 'marquee'), '0')
                        fetchImage(str_snap_url, img_snap,
                                    os.path.join(imgroot, 'snap'), '1')

                    if str_rd is not None:
                        releasedate.text=str_rd

                    if str_pub is not None:
                        publisher.text=str_pub

                    if str_dev is not None:
                        developer.text=str_dev

                    if lst_genres is not None:
                        for genre in lst_genres:
                            newgenre = SubElement(genres, 'genre')
                            newgenre.text=genre.strip()
        except KeyboardInterrupt:
            print "Ctrl+C detected. Closing work now..."
        except Exception as e:
            print "Exception caught! %s" % e

    if gamelist.find("game") is None:
        print "No new games added."
    else:
        print "{} games added.".format(len(gamelist))
        exportList(gamelist)

try:
    if os.getuid()==0:
        os.environ['HOME']="/home/"+os.getenv("SUDO_USER")
    config=open(os.environ['HOME']+"/.emulationstation/es_systems.cfg")
except IOError as e:
    sys.exit("Error when reading config file: %s \nExiting.." % e.strerror)

ES_systems=readConfig(config)
print parser.description

if args.w:
    print "Max width set: %spx." % str(args.w)
if args.noimg:
    print "Boxart downloading disabled."
if args.f:
    print "Re-scraping all games.."
if args.v:
    print "Verbose mode enabled."
if args.crc:
    print "CRC scraping enabled."
if args.p:
    print "Partial scraping enabled. Systems found:"
    for i,v in enumerate(ES_systems):
        print "[%s] %s" % (i,v[0])
    try:
        var = int(raw_input("System ID: "))
        scanFiles(ES_systems[var])
    except:
        sys.exit()
else:
    for i,v in enumerate(ES_systems):
        scanFiles(ES_systems[i])

print "All done!"
