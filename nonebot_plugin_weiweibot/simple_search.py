from .data import extract_name
from random import choice
from pathlib import Path

name = []
ex_name = []
very_ex_name=[]
__dir = Path(__file__).parent
for filename in __dir.joinpath("assets").iterdir():
    if filename.suffix.lower() in ['.png', '.jpg', '.jpeg', '.bmp', '.gif']:
        name.append(filename.name)
        ex_name.append(extract_name(filename.name, mod=0))
        very_ex_name.append(extract_name(filename.name))

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

def name_handler():
    return name
    
