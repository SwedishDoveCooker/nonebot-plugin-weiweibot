import os
from data import extract_name
from random import choice

name = []
ex_name = []
very_ex_name=[]
for filename in os.listdir("./assets"):
    if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
        name.append(filename)
        ex_name.append(extract_name(filename, mod=0))
        very_ex_name.append(extract_name(filename))

def simple_search(key_words, mod):
    results = []
    if mod:
        for i in range(len(name)):
            if key_words in ex_name[i].lower():
                results.append([i,name[i],ex_name[i]])
        if mod==1:
            return results
        else:
            return results
    else:
        return choice(name)

def very_ex_name_handler():
    return very_ex_name
    
