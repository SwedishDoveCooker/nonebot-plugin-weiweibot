import re
import math
from collections import defaultdict

def custom_tokenize(text):
    text = re.sub(r'\s+', '', text)
    result = []
    temp = []
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            if temp:
                result.append(''.join(temp))
                temp = []
            result.append(char)
        else:
            temp.append(char.lower())
    if temp:
        result.append(''.join(temp))
    return result

def compute_word_frequencies(corpus):
    word_freq = defaultdict(int)
    for text in corpus:
        words = custom_tokenize(text)
        for word in words:
            word_freq[word] += 1
    return word_freq

def compute_idf(corpus):
    num_documents = len(corpus)
    word_doc_freq = defaultdict(int)
    for text in corpus:
        words = set(custom_tokenize(text))
        for word in words:
            word_doc_freq[word] += 1

    idf = {}
    for word, doc_freq in word_doc_freq.items():
        idf[word] = math.log(num_documents / (1 + doc_freq))
    return idf

def score_document(query, document, idf):
    query_words = custom_tokenize(query)
    document_words = custom_tokenize(document)
    score = 0
    for word in query_words:
        if word in document_words:
            score += idf.get(word, 0)
    return score

def rank_documents(query, corpus, idf):
    scores = [(index, score_document(query, doc, idf)) for index, doc in enumerate(corpus)]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores

