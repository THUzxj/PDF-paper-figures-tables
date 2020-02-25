from django.http import HttpResponseRedirect
from django.http import HttpResponse
from django.shortcuts import render
from . import pdfmining

def handle_uploaded_file(f,path):
    with open(path+f.name, 'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)

def upload(request):
    ret={}
    if(request.method == 'POST'):
        f=request.FILES.get('f',None)
        if not f:
            ret['name']="No file uploaded!"
            return render(request,'showpdf.html',ret)
        handle_uploaded_file(f,"./static/")
        ret['name']=f.name
        pdf=pdfmining.pdfTitleMiner("./static/"+f.name)
        pdf.mine()
        pdf.init_cv()
        figure_paths=pdf.save_figures("./static/")
        table_paths=pdf.save_tables("./static/")
        figure_titles=pdf.get_figure_titles()
        table_titles=pdf.get_table_titles()
        page_num=pdf.page_num
        #figure_paths=[[] for i in range(page_num)]
        #table_paths=[[] for i in range(page_num)]
        pages=[]
        for index in range(page_num):
            fnum=min(len(figure_paths[index]),len(figure_titles[index]))
            tnum=min(len(table_paths[index]),len(table_titles[index]))
            f=[]
            t=[]
            for i in range(fnum):
                f.append((figure_titles[index][i],figure_paths[index][i]))
            if(len(figure_paths[index])>fnum):
                for i in range(fnum,len(figure_paths[index])):
                    f.append(("Not Found",figure_paths[index][i]))
            if(len(figure_titles[index])>fnum):
                for i in range(fnum,len(figure_titles[index])):
                    f.append((figure_titles[index][i],"Not Found"))
            for i in range(tnum):
                t.append((table_titles[index][i],table_paths[index][i]))
            if(len(table_paths[index])>tnum):
                for i in range(tnum,len(table_paths[index])):
                    t.append(("Not Found",table_paths[index][i]))
            if(len(table_titles[index])>tnum):
                for i in range(tnum,len(table_titles[index])):
                    t.append((table_titles[index][i],"Not Found"))
                    
            pages.append((f,t))
        ret['pages']=pages
        table_texts=pdf.extract_table_text()
        ret['tables']=table_texts
        ret['paper_title']=pdf.get_paper_title()

    return render(request,'showpdf.html',ret)
