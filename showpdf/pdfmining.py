from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfpage import PDFTextExtractionNotAllowed
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfdevice import PDFDevice
#layout analysis
from pdfminer.layout import *
from pdfminer.converter import PDFPageAggregator
from pdf2image import convert_from_path
import pdfplumber
import PyPDF2

import re
import os
import cv2
import numpy as np
import sys
from math import sqrt

def mkdir(path):
    folder=os.path.exists(path)
    if not folder:
        os.mkdir(path)

def midPoint(x):
    return ((x.bbox[0]+x.bbox[2])/2,(x.bbox[1]+x.bbox[3])/2)

def trans(origin,height):
    #The coodinate usages in PDFMiner and OpenCV are different
    #round() get the biggest integer smaller than the number
    box=(origin[0], height-origin[3], origin[2], height-origin[1])
    return tuple([round(a) for a in box])

#input are a LTobject and the page_width
def positionClassifier(x,width):
    mid=width/2
    if(x.bbox[0]<mid and x.bbox[2]<mid):
        return 'left'
    elif(x.bbox[0]>=mid and x.bbox[2]>=mid):
        return 'right'
    else:
        return 'middle'

def rectDistance(x,y):
    a=x.bbox
    b=y.bbox
    isInversion=None
    point1=None
    point2=None
    if(a[1]<b[1]):
        isInversion=a[0]<b[0]
        if(isInversion):
            point1=a[2:]
            point2=b[:2]
        else:
            point1=[a[0],a[3]]
            point2=[b[2],b[1]]
    else:
        isInversion=a[0]>b[0]
        if(isInversion):
            point2=a[:2]
            point1=b[2:]
        else:
            point2=[a[2],a[1]]
            point1=[b[0],b[3]]
    dpoint=[point2[0]-point1[0],point2[1]-point1[1]]
    if(isInversion==False):
        dpoint[0]=-dpoint[0]
    if(dpoint[0]<0 and dpoint[1]<0):
        return -1
    if(dpoint[0]<0):
        return dpoint[1]
    if(dpoint[1]<0):
        return dpoint[0]
    return sqrt(dpoint[0]**2+dpoint[1]**2)

def inRect(rect,point):
    return point[0]>rect[0] and point[0]<rect[2] and point[1]>rect[1] and point[1]<rect[3]

#input are 2 numbers
def equal(a,b):
    return abs(a-b)<=2

def expand(a,b):
    if(a==None):
        return b
    if(b==None):
        return a
    return (min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3]))

class notFound:
    def __init__(self):
        self.bbox=(-1,-1,-1,-1)
    def get_text(self):
        return "notFound"

class figure:
    def __init__(self,obj):
        self.obj=obj
        self.bbox=obj.bbox
        self.title=None
    def setTitle(self,tit):
        self.title=tit.get_text()
        self.contentbbox=self.bbox
        if(tit.bbox[0]==-1):
            return
        self.bbox=expand(self.bbox,tit.bbox)

class figureGroup:
    def __init__(self,firstFigure):
        self.figures=[firstFigure]
        self.bbox=firstFigure.bbox
    def addFigure(self,fig):
        self.figures.append(fig)
        #expand the bound
        self.bbox=expand(self.bbox,fig.bbox)
        self.contentbbox=expand(self.contentbbox,fig.bbox)
    def setTitle(self,tit):
        self.title=tit.get_text()
        self.contentbbox=self.bbox
        if(tit.bbox[0]==-1):
            return
        self.bbox=expand(self.bbox,tit.bbox)

class mergedText:
    def __init__(self,head,textList):
        self.head=head
        self.textList=textList
        self.text=head.get_text()
        self.bbox=head.bbox
        self.merge()
    def merge(self):
        if(self.bbox[0]==-1):
            return
        x=0
        for index in range(len(self.textList)):
            if(self.head==self.textList[index]):
                x=index
                break
        for index in range(x+1,len(self.textList)):
            if(rectDistance(self.textList[index],self.textList[index-1])==-1):
                self.text+=self.textList[index].get_text()
                self.bbox=expand(self.bbox,self.textList[index].bbox)
            else:
                break
    def get_text(self):
        return self.text

class Table:
    def __init__(self,newLine=None):
        if(newLine==None):
            self.bbox=None
            self.lineNum=0
            self.lines=[]
        else:
            self.bbox=newLine.bbox
            self.lineNum=1
            self.lines=[newLine.bbox]
    def addLine(self,newLine):
        self.bbox=expand(self.bbox,newLine.bbox)
        self.lineNum+=1
        self.lines.append(newLine.bbox)
    def setLines(self,newLines):
        self.lines=newLines
        self.lineNum=len(newLines)
        for x in newLines:
            self.bbox=expand(self.bbox,x)
    def setTitle(self,tit):
        self.title=tit.get_text()
        self.contentbbox=self.bbox
        if(tit.bbox[0]==-1):
            return
        self.bbox=expand(self.bbox,tit.bbox)

color = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (160, 32, 240)]
    #        red          green        blue         yellow         purple
object_type = ['Object','TextBox','Figure','Line']
layout_type = ['LTTextBox', 'LTFigure', 'LTLine']
elem_type = ['Figure','Table','Algorithm']
candidate_settings = {'left':('left','middle'),'middle':('left','middle','right'),'right':('right','middle')}


class pdfTitleMiner:
    def __init__(self,path):
        self.num={x : 0 for x in object_type}
        self.elem={x : [] for x in elem_type}
        #PDFplumber
        self.pdfpl=pdfplumber.open(path)
        #convert pdf to image
        self.path=path
        self.layouts=[]
        self.page_num=0
        self.fp=open(self.path,'rb')

    def init_cv(self,dpi=200):
        self.image = convert_from_path(self.path,dpi=dpi)

    def get_paper_title(self):
        reader=PyPDF2.PdfFileReader(self.fp)
        self.data=reader.getDocumentInfo()
        return self.data['/Title']

    def save_figures(self,path):
        paths=[]
        for index in range(self.page_num):
            page_paths=[]
            num=0
            image_pil = self.image[index]
            image_numpy=np.array(image_pil)
            page_width,page_height=self.layouts[index].bbox[2:4]
            original_image = cv2.resize(image_numpy, (page_width,page_height), interpolation=cv2.INTER_AREA)
            for x in self.elem['Figure'][index]:
                real_box_integer=trans(x.contentbbox,page_height)
                new_img=original_image[real_box_integer[1]:real_box_integer[3],real_box_integer[0]:real_box_integer[2]]
                file_name="figure"+str(index)+"-"+str(num)+".png"
                cv2.imwrite(path+file_name,new_img)
                num+=1
                page_paths.append(file_name)
            paths.append(page_paths)
        return paths

    def save_tables(self,path):
        paths=[]
        for index in range(self.page_num):
            page_paths=[]
            num=0
            image_pil = self.image[index]
            image_numpy=np.array(image_pil)
            page_width,page_height=self.layouts[index].bbox[2:4]
            original_image = cv2.resize(image_numpy, (page_width,page_height), interpolation=cv2.INTER_AREA)
            for x in self.elem['Table'][index]:
                real_box_integer=trans(x.contentbbox,page_height)
                new_img=original_image[real_box_integer[1]:real_box_integer[3],real_box_integer[0]:real_box_integer[2]]
                file_name="table"+str(index)+"-"+str(num)+".png"
                cv2.imwrite(path+file_name,new_img)
                num+=1
                page_paths.append(file_name)
            paths.append(page_paths)
        return paths
    
    def visualize(self,path,All=False,Figure=False,Table=False):
        for index in range(self.page_num):
            image_pil = self.image[index]
            image_numpy=np.array(image_pil)
            page_width,page_height=self.layouts[index].bbox[2:4]
            added_image = cv2.resize(image_numpy, (page_width,page_height), interpolation=cv2.INTER_AREA)
            if(All==True):
                Figure=True
                Table=True
            if(Figure==True):
                for x in self.elem['Figure'][index]:
                    real_box_integer=trans(x.contentbbox,page_height)
                    cv2.rectangle(added_image,real_box_integer[:2],real_box_integer[2:],color[0],1)
            if(Table==True):
                for x in self.elem['Table'][index]:
                    real_box_integer=trans(x.contentbbox,page_height)
                    cv2.rectangle(added_image,real_box_integer[:2],real_box_integer[2:],color[1],1)
            file_path=path+str(index)+".png"
            cv2.imwrite(file_path,added_image)
    
    def text_in_rect(self,rect,textList):
        text=[]
        for textBox in textList:
            if(rectDistance(rect,textBox)==-1):
                text.append(textBox)
        return text

    def extract_table_text(self):
        all_tables=[]
        for index in range(self.page_num):
            pagepl=self.pdfpl.pages[index]
            tablespl=pagepl.extract_tables()
            valid_tables=[]
            for table in tablespl:
                isValid=True
                for row in table:
                    for elem in row:
                        if(elem==None):
                            isValid=False
                            break
                    if(isValid==False):
                        break
                if(isValid==True):
                    valid_tables.append(table)    
            all_tables.append(valid_tables)
        return all_tables

    def get_figure_titles(self):
        figure_titles=[]
        for index in range(self.page_num):
            page_titles=[]
            for x in self.elem['Figure'][index]:
                page_titles.append(x.title)
            figure_titles.append(page_titles)
        return figure_titles

    def get_table_titles(self):
        table_titles=[]
        for index in range(self.page_num):
            page_titles=[]
            for x in self.elem['Table'][index]:
                page_titles.append(x.title)
            table_titles.append(page_titles)
        return table_titles        

    def mine(self):
        #PDFMiner
        parser=PDFParser(self.fp)
        document=PDFDocument(parser)
        if not document.is_extractable:
            raise PDFTextExtractionNotAllowed
        laparams = LAParams()
        rsrcmgr = PDFResourceManager()
        device = PDFPageAggregator(rsrcmgr,laparams=laparams)
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        pages=PDFPage.create_pages(document)
        index=0
        for page in pages:
            interpreter.process_page(page)
            layout=device.get_result()
            self.layouts.append(layout)
            self.page_num+=1

            counter={x : 0 for x in object_type}
            page_height=layout.bbox[3]
            page_width=layout.bbox[2]
            page_elem={x : [] for x in elem_type}

            figure_groups={}
            textBoxs={'left':[],'middle':[],'right':[],'all':[]}
            line_groups=[]

            for x in layout:
                if(isinstance(x,LTTextBox)):
                    textBoxs[positionClassifier(x,page_width)].append(x)
                    textBoxs['all'].append(x)
                    counter['TextBox']+=1
                elif(isinstance(x,LTFigure)):
                    if(x.bbox[3]-x.bbox[1]<5):
                        continue
                    #find figure title (the nearest textbox)
                    #the numbers of figures and textboxs are not so big
                    minn=100000000
                    title=None
                    candidate=candidate_settings[positionClassifier(x,page_width)]
                    for group in candidate:
                        for y in textBoxs[group]:
                            if(x.bbox[1]<y.bbox[3]):
                                continue
                            dst=rectDistance(x,y)
                            if(dst<minn):
                                minn=dst
                                title=y
                    if(title==None):
                        title=notFound()
                    #merge the near textBoxs
                    title_merged=mergedText(title,textBoxs['all'])
                    title_text=title_merged.text
                    #check the subtitle
                    if(title_text[0]=='(' or len(title_text)<20):
                        #find the below title
                        big_title=None
                        minn=100000000
                        for group in candidate:
                            for y in textBoxs[group]:
                                if(x.bbox[1]<y.bbox[3] or y.get_text()[0]=='('):
                                    continue
                                dst=rectDistance(x,y)
                                if(dst<minn):
                                    minn=dst
                                    big_title=y
                        big_title_text=big_title.get_text()
                        if big_title_text in figure_groups:
                            #加入到已有组中
                            add_sub=figure(x)
                            add_sub.setTitle(title_merged)
                            figure_groups[big_title_text].addFigure(add_sub)
                        else:
                            #创建新组
                            fst_sub=figure(x)
                            fst_sub.setTitle(title_merged)
                            new_group=figureGroup(fst_sub)
                            new_group.setTitle(big_title)
                            figure_groups[big_title_text]=new_group
                            page_elem['Figure'].append(new_group)
                    else:
                        title_text=title_merged.get_text()
                        if title_text in figure_groups:
                            add_sub=figure(x)
                            figure_groups[title_text].addFigure(add_sub)
                        else:
                            new_fig=figure(x)
                            new_group=figureGroup(new_fig)
                            new_group.setTitle(title_merged)
                            figure_groups[title_text]=new_group
                            page_elem['Figure'].append(new_group)
                    counter['Figure']+=1
                elif(isinstance(x,LTLine)):
                    #horizontal lines
                    if(equal(x.bbox[1],x.bbox[3])):
                        flag=False
                        for table in line_groups:
                            if(equal(table.bbox[0],x.bbox[0]) and equal(table.bbox[2],x.bbox[2])):
                                table.addLine(x)
                                flag=True
                                break
                        if(flag==False):
                            new_table=Table(x)
                            line_groups.append(new_table)
                    counter['Line']+=1
                counter['Object']+=1

            for x in object_type:
                self.num[x]+=counter[x]

            #find tables
            for table in line_groups:
                if(table.lineNum>=2 and table.bbox[2]-table.bbox[0]>50):
                    text=self.text_in_rect(table,textBoxs['all'])
                    if(len(text)!=0):
                        if(re.search("Algorithm",text[0].get_text())):
                            page_elem['Algorithm'].append(table)
                            continue
                    #split lines into groups
                    divided=[]
                    for i in range(1,len(table.lines)):
                        divided.append([])
                    for t in text:
                        mid_y=midPoint(t)[1]
                        for i in range(1,len(table.lines)):
                            if(mid_y>table.lines[i][1]):
                                divided[i-1].append(t)
                                break
                    split_tables=[]
                    prev_i=0
                    for i in range(len(table.lines)-1):
                        if(len(divided[i])==0):
                            continue
                        if(len(divided[i])==1 and not (divided[i][0].bbox[0]>table.bbox[0] and divided[i][0].bbox[2]<table.bbox[2])):
                            new_table=Table()
                            new_table.setLines(table.lines[prev_i:i+1])
                            prev_i=i+1
                            split_tables.append(new_table)
                    new_table=Table()
                    new_table.setLines(table.lines[prev_i:len(table.lines)])
                    split_tables.append(new_table)
                    for split_table in split_tables:
                        minn=100000000
                        title=None
                        candidate=candidate_settings[positionClassifier(split_table,page_width)]
                        for group in candidate:
                            for y in textBoxs[group]:
                                #the title is above the table
                                if(split_table.bbox[3]>y.bbox[1]):
                                    continue
                                dst=rectDistance(table,y)
                                if(dst<minn):
                                    minn=dst
                                    title=y
                        if(title==None):
                            title=notFound()
                        title_merged=mergedText(title,textBoxs['all'])
                        split_table.setTitle(title_merged)
                        page_elem['Table'].append(split_table)
                        
            for x in elem_type:
                self.elem[x].append(page_elem[x])
            index+=1
