#!/usr/bin/env python
import os
import sys
from ricecooker.utils import data_writer, path_builder, downloader, html_writer
from le_utils.constants import licenses, exercises, content_kinds, file_formats, format_presets, languages

from collections import OrderedDict
import logging
import os
from pathlib import Path
import re
import sys
import time
import copy
from urllib.error import URLError
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup
from le_utils.constants import licenses, file_formats
import json
import requests
from ricecooker.classes.files import download_from_web, config
from ricecooker.utils.caching import CacheForeverHeuristic, FileCache, CacheControlAdapter


# Channel constants
################################################################################
CHANNEL_NAME = "Teach Engineering"              # Name of channel
CHANNEL_SOURCE_ID = "teachengineering-en"    # Channel's unique id
CHANNEL_DOMAIN = "teachengineering.org"          # Who is providing the content
CHANNEL_LANGUAGE = "en"      # Language of channel
CHANNEL_DESCRIPTION = None                                  # Description of the channel (optional)
CHANNEL_THUMBNAIL = None                                    # Local path or url to image file (optional)
PATH = path_builder.PathBuilder(channel_name=CHANNEL_NAME)  # Keeps track of path to write to csv
WRITE_TO_PATH = "{}{}{}.zip".format(os.path.dirname(os.path.realpath(__file__)), os.path.sep, CHANNEL_NAME) # Where to generate zip file

# Additional Constants
################################################################################
LOGGER = logging.getLogger()
__logging_handler = logging.StreamHandler()
LOGGER.addHandler(__logging_handler)
LOGGER.setLevel(logging.INFO)

# BASE_URL is used to identify when a resource is owned by Edsitement
BASE_URL = "https://www.teachengineering.org"

# If False then no download is made
# for debugging proporses
DOWNLOAD_VIDEOS = False

# time.sleep for debugging proporses, it helps to check log messages
TIME_SLEEP = .2


# Main Scraping Method
################################################################################
def scrape_source(writer):
    """
    Scrapes channel page and writes to a DataWriter
    Args: writer (DataWriter): class that writes data to folder/spreadsheet structure
    Returns: None
    """
    CURRICULUM_BROWSE_URL = urljoin(BASE_URL, "curriculum/browse")
    LOGGER.info("Checking data from: " + CURRICULUM_BROWSE_URL)
    #resource_browser = ResourceBrowser(CURRICULUM_BROWSE_URL)
    #resource_browser.run()
    #url = "https://www.teachengineering.org/activities/view/cub_human_lesson06_activity1"
    #url = "https://www.teachengineering.org/lessons/view/van_mri_lesson_7"
    url = "https://www.teachengineering.org/activities/view/wpi_amusement_park_ride"
    try:
        subtopic_name = "test"
        document = downloader.read(url, loadjs=False)#, session=sess)
        page = BeautifulSoup(document, 'html.parser')
        collection = Collection(page, filepath="/tmp/lesson-"+subtopic_name+".zip", 
            source_id=url)
        collection.to_file(PATH, ["activities"])
    except requests.exceptions.HTTPError as e:
        LOGGER.info("Error: {}".format(e))


class ResourceBrowser(object):
    def __init__(self, resource_url):
        self.resource_url = resource_url

    def get_resource_data(self):
        try:
            page_contents = downloader.read(self.resource_url, loadjs=True)#, session=sess)
        except requests.exceptions.HTTPError as e:
            LOGGER.info("Error: {}".format(e))
        page = BeautifulSoup(page_contents, 'html.parser')
        scripts = page.find_all("script")
        keys = ["serviceName", "indexName", "apiKey", "apiVersion"]
        azureSearchSettings = {}
        for scriptjs in scripts:
            textValue = scriptjs.text
            try:
                for elem in textValue.split('{', 1)[1].rsplit('}', 1):
                    for kv in elem.split(","):
                        try:
                            k, v = kv.split(":")
                            k = k.strip().replace('"', "").replace("'", "")
                            v = v.strip().replace('"', "").replace("'", "")
                            if k in keys:
                                azureSearchSettings[k] = v 
                        except ValueError:
                            pass
            except IndexError:
                pass
        return azureSearchSettings

    def build_resource_url(self, azureSearchSettings, offset=0):
        return "https://{serviceName}.search.windows.net/indexes/{indexName}/docs?api-version={apiVersion}&api-key={apiKey}&search=&%24count=true&%24top=10&%24skip={offset}&searchMode=all&scoringProfile=FieldBoost&%24orderby=sortableTitle".format(offset=offset, **azureSearchSettings)

    def run(self):
        settings = self.get_resource_data()
        offset = 0
        while True:
            url = self.build_resource_url(settings, offset=offset)
            req = requests.get(url)
            data = req.json()
            #num_registers = data["@odata.count"]
            for resource in data["value"]:
                url = self.build_resource_url(resource["id"], resource["collection"])
                try:
                    document = downloader.read(self.resource_url, loadjs=False)#, session=sess)
                    page = BeautifulSoup(document, 'html.parser')
                except requests.exceptions.HTTPError as e:
                    LOGGER.info("Error: {}".format(e))
                else:
                    collection = Collection(page, filepath="/tmp/"+resource["id"]+".zip", 
                        source_id=url)
                    collection.to_file(PATH, [resource["collection"]])
                    time.sleep(1)
                break
            return

    def build_resource_url(id_name, collection):
        return urljoin(BASE_URL, collection.lower()+"/view/"+id_name)


class Menu(object):
    """
        This class checks elements on the lesson menu and build the menu list
    """
    def __init__(self, page, filename=None, id_=None, exclude_titles=None):
        self.body = page.find("div", id=id_)
        self.menu = OrderedDict()
        self.filename = filename
        self.exclude_titles = [] if exclude_titles is None else exclude_titles
        self.menu_titles(self.body.find_all("li"))

    def write(self, content):
        with html_writer.HTMLWriter(self.filename, "w") as zipper:
            zipper.write_index_contents(content)

    def to_file(self):
        self.write('<html><body><meta charset="UTF-8"></head><ul>'+self.to_html()+'</ul></body></html>')

    def menu_titles(self, titles):
        for title in titles:
            self.add(title.text)

    def get(self, name):
        try:
            return self.menu[name]["filename"]
        except KeyError:
            return None

    def add(self, title):
        name = title.lower().strip().replace(" ", "_").replace("/", "_")
        if not name in self.exclude_titles:
            self.menu[name] = {
                "filename": "{}.html".format(name),
                "text": title,
                "section": None,
            }

    def set_section(self, name, section):
        self.menu[name]["section"] = section

    def to_html(self, directory="files/", active_li=None):
        li = []
        for e in self.menu.values():
            li.append("<li>")
            if active_li is not None and e["filename"] == active_li:
                li.append('{text}'.format(text=e["text"]))
            else:
                li.append('<a href="{directory}{filename}">{text}</a>'.format(directory=directory, **e))
            li.append("</li>")
        return "".join(li)

    def check(self):
        for name, values in self.menu.items():
            if values["section"] is None:
                print(name, "is not linked to a section")
                raise Exception


class Collection(object):
    def __init__(self, page, filepath, source_id):
        self.page = page
        self.title_prefix = self.clean_title(self.page.find("span", class_="title-prefix"))
        self.title = self.clean_title(self.page.find("span", class_="curriculum-title"))
        self.contribution_by = None
        self.menu = Menu(self.page, filename=filepath, id_="CurriculumNav", 
            exclude_titles=["attachments", "comments"])
        self.menu.add("Contributors")
        self.source_id = source_id
        self.sections = [
            [Summary, EngineeringConnection],
            LearningObjetives,
            MoreLikeThis,
            MaterialsList,
            Introduction,
            Background,
            Vocabulary,
            Procedure,
            InvestigatingQuestions,
            Troubleshooting,
            Assessment,
            ActivityExtensions,
            ActivityScaling,
            References,
            [Contributors, SupportingProgram, Acknowledgements, Copyright]
        ]

    def clean_title(self, title):
        if title is not None:
            return title.text.strip()
        return title

    def to_file(self, PATH, levels):
        LOGGER.info(" + Curriculum:"+ self.title)
        self.menu.to_file()
        copy_page = copy.copy(self.page)
        for Section in self.sections:
            if isinstance(Section, list):
                section = sum([section(self.page, filename=self.menu.filename) 
                                for section in Section])
            else:
                section = Section(self.page, filename=self.menu.filename)
            menu_filename = self.menu.get(section.menu_name)
            if menu_filename is not None:
                print(section.id, section.__class__.__name__)
                self.menu.set_section(section.menu_name, section.id)
            menu_index = self.menu.to_html(directory="", active_li=menu_filename)
            section.to_file(menu_filename, menu_index=menu_index)

        self.menu.check()
        cr = Copyright(copy_page)
        metadata_dict = {"description": "",
            "language": "en",
            "license": licenses.CC_BY,
            "copyright_holder": cr.get_copyright_info(),
            "author": "",
            "source_id": self.source_id}

        levels.append(self.title.replace("/", "-"))
        PATH.set(*levels)
        writer.add_file(str(PATH), "Curriculum", self.menu.filename, **metadata_dict)
        attachments = Attachments(self.page)
        writer.add_folder(str(PATH), "Attachments", **metadata_dict)
        PATH.set(*(levels+["Attachments"]))
        for name, pdf_url in attachments.get_pdfs():
            meta = metadata_dict.copy()
            meta["source_id"] = pdf_url
            try:
                writer.add_file(str(PATH), name.replace(".pdf", ""), pdf_url, **meta)
            except requests.exceptions.HTTPError as e:
                LOGGER.info("Error: {}".format(e))
        if if_file_exists(self.menu.filename):
            #writer.add_file(str(PATH), "MEDIA", self.resources.filename, **metadata_dict)
            self.rm(self.menu.filename)
        
        PATH.go_to_parent_folder()
        PATH.go_to_parent_folder()

    def rm(self, filepath):
        os.remove(filepath)


class CollectionSection(object):
    def __init__(self,  page, filename=None, id_=None, menu_name=None):
        LOGGER.debug(id_)
        self.id = id_
        if id_ is not None:
            self.body = page.find("section", id=id_)
        else:
            self.body = None

        if self.body is not None:
            h3 = self.body.find("h3")
            self.title = self.clean_title(h3)
            del h3
        else:
            self.title = None
        self.filename = filename
        self.menu_name = menu_name

    def __add__(self, o):
        from bs4 import Tag
        
        if isinstance(self.body, Tag) and isinstance(o.body, Tag):
            parent = Tag(name="div")
            parent.insert(0, self.body)
            parent.insert(1, o.body)
            self.body = parent
        else:
            LOGGER.info("Not merged sections: " + self + " and "+ o)

        return self

    def __radd__(self, o):
        return self

    def clean_title(self, title):
        if title is not None:
            title = str(title)
        return title

    def get_content(self):
        content = self.body
        self.get_imgs()
        remove_links(content)
        return "".join([str(p) for p in content])

    def get_imgs(self):
        for img in self.body.find_all("img"):
            if img["src"].startswith("/"):
                img_src = urljoin(BASE_URL, img["src"])
            else:
                img_src = img["src"]
            filename = get_name_from_url(img_src)
            self.write_img(img_src, filename)
            img["src"] = filename

    def write(self, filename, content):
        with html_writer.HTMLWriter(self.filename, "a") as zipper:
            zipper.write_contents(filename, content, directory="files")

    def write_img(self, url, filename):
        with html_writer.HTMLWriter(self.filename, "a") as zipper:
            zipper.write_url(url, filename, directory="files")

    def to_file(self, filename, menu_index=None):
        if self.body is not None and filename is not None:
            content = self.get_content()

            if menu_index is not None:
                html = '<html><head><meta charset="UTF-8"></head><body>{}{}<body></html>'.format(
                    menu_index, content)
            else:
                html = '<html><head><meta charset="UTF-8"></head><body>{}<body></html>'.format(
                    content)

            self.write(filename, html)


class Summary(CollectionSection):
    def __init__(self, page, filename=None):
        super(Summary, self).__init__(page, filename=filename,
                id_="summary", menu_name="summary")


class EngineeringConnection(CollectionSection):
    def __init__(self, page, filename=None):
        super(EngineeringConnection, self).__init__(page, filename=filename,
                id_="engineering_connection", menu_name="engineering_connection")
        self.body = page.find(lambda tag: tag.name=="section" and\
            tag.findChildren("h3", text=re.compile("\s*Engineering Connection\s*")))


class LearningObjetives(CollectionSection):
    def __init__(self, page, filename=None):
        super(LearningObjetives, self).__init__(page, filename=filename,
                id_="objectives", menu_name="learning_objectives")


class MoreLikeThis(CollectionSection):
    def __init__(self, page, filename=None):
        super(MoreLikeThis, self).__init__(page, filename=filename,
                id_="morelikethis", menu_name="more_like_this")


class MaterialsList(CollectionSection):
    def __init__(self, page, filename=None):
        super(MaterialsList, self).__init__(page, filename=filename,
                id_="mats", menu_name="materials_list")


class Introduction(CollectionSection):
    def __init__(self, page, filename=None):
        super(Introduction, self).__init__(page, filename=filename,
                id_="intro", menu_name="introduction_motivation")


class Procedure(CollectionSection):
    def __init__(self, page, filename=None):
        super(Procedure, self).__init__(page, filename=filename,
                id_="procedure", menu_name="procedure")


class Attachments(CollectionSection):
    def __init__(self, page, filename=None):
        super(Attachments, self).__init__(page, filename=filename,
                id_="attachments", menu_name="attachments")

    def get_pdfs(self):
        resource_links = self.body.find_all("a", href=re.compile("^\/|https\:\/\/www.teachengineering"))
        for link in resource_links:
            if link["href"].endswith(".pdf"):
                name = get_name_from_url(link["href"])
                yield name, urljoin(BASE_URL, link["href"])


class Troubleshooting(CollectionSection):
    def __init__(self, page, filename=None):
        super(Troubleshooting, self).__init__(page, filename=filename,
                id_="troubleshooting", menu_name="troubleshooting_tips")


class Assessment(CollectionSection):
    def __init__(self, page, filename=None, id_=None, menu_name=None):
        super(Assessment, self).__init__(page, filename=filename,
                id_="assessment", menu_name="assessment")


class ActivityExtensions(CollectionSection):
    def __init__(self, page, filename=None, id_=None, menu_name=None):
        super(ActivityExtensions, self).__init__(page, filename=filename,
                id_="extensions", menu_name="activity_extensions")


class References(CollectionSection):
    def __init__(self, page, filename=None):
        super(References, self).__init__(page, filename=filename,
                id_="references", menu_name="references")


class Contributors(CollectionSection):
    def __init__(self, page, filename=None):
        super(Contributors, self).__init__(page, filename=filename,
                id_="contributors", menu_name="contributors")
        self.body = page.find(lambda tag: tag.name=="section" and\
            tag.findChildren("h3", text=re.compile("\s*Contributors\s*")))


class SupportingProgram(CollectionSection):
    def __init__(self, page, filename=None):
        super(SupportingProgram, self).__init__(page, filename=filename,
                id_="supporting_program", menu_name="supporting_program")
        self.body = page.find(lambda tag: tag.name=="section" and\
            tag.findChildren("h3", text=re.compile("\s*Supporting Program\s*")))


class Acknowledgements(CollectionSection):
    def __init__(self, page, filename=None):
        super(Acknowledgements, self).__init__(page, filename=filename,
                id_="acknowledgements", menu_name="acknowledgements")
        self.body = page.find(lambda tag: tag.name=="section" and\
            tag.findChildren("h3", text=re.compile("\s*Acknowledgements\s*")))


class Copyright(CollectionSection):
    def __init__(self, page, filename=None):
        super(Copyright, self).__init__(page, filename=filename,
                id_="copyright", menu_name="copyright")
        self.body = page.find(lambda tag: tag.name=="section" and\
            tag.findChildren("h3", text=re.compile("\s*Copyright\s*")))

    def get_copyright_info(self):
        text = self.body.text
        index = text.find("©")
        if index != -1:
            copyright = text[index:].strip()
            LOGGER.info("   - COPYRIGHT INFO:" + copyright)
        else:
            copyright = ""
        return copyright


class Background(CollectionSection):
    def __init__(self, page, filename=None):
        super(Background, self).__init__(page, filename=filename,
                id_="background", menu_name="background")


class Vocabulary(CollectionSection):
    def __init__(self, page, filename=None):
        super(Vocabulary, self).__init__(page, filename=filename,
                id_="vocab", menu_name="vocabulary_definitions")


class InvestigatingQuestions(CollectionSection):
    def __init__(self, page, filename=None):
        super(InvestigatingQuestions, self).__init__(page, filename=filename,
                id_="quest", menu_name="investigating_questions")


class ActivityScaling(CollectionSection):
    def __init__(self, page, filename=None):
        super(ActivityScaling, self).__init__(page, filename=filename,
                id_="scaling", menu_name="activity_scaling")


def if_file_exists(filepath):
    file_ = Path(filepath)
    return file_.is_file()


def get_name_from_url(url):
    return os.path.basename(urlparse(url).path)


def get_name_from_url_no_ext(url):
    path = get_name_from_url(url)
    return ".".join(path.split(".")[:-1])


def remove_links(content):
    if content is not None:
        for link in content.find_all("a"):
            link.replaceWithChildren()


# CLI: This code will run when `souschef.py` is called on the command line
################################################################################
if __name__ == '__main__':
    # Open a writer to generate files
    with data_writer.DataWriter(write_to_path=WRITE_TO_PATH) as writer:
        # Write channel details to spreadsheet
        thumbnail = writer.add_file(str(PATH), "Channel Thumbnail", CHANNEL_THUMBNAIL, write_data=False)
        writer.add_channel(CHANNEL_NAME, CHANNEL_SOURCE_ID, CHANNEL_DOMAIN, CHANNEL_LANGUAGE, description=CHANNEL_DESCRIPTION, thumbnail=thumbnail)
        # Scrape source content
        scrape_source(writer)
        sys.stdout.write("\n\nDONE: Zip created at {}\n".format(writer.write_to_path))
