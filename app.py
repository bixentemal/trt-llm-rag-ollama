# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
import argparse
import os
import time
import json
import logging
import gc
import torch
from pathlib import Path

from langchain.embeddings.huggingface import HuggingFaceEmbeddings
from collections import defaultdict
from llama_index import ServiceContext
from llama_index import set_global_service_context
from llama_index.core.response.schema import RESPONSE_TYPE
#from llama_index.llms import OpenAI

from faiss_vector_storage import FaissEmbeddingStorage
from ui.user_interface import MainInterface
from llama_index.llms.ollama import Ollama

app_config_file = 'config/app_config.json'
model_config_file = 'config/config.json'
preference_config_file = 'config/preferences.json'
data_source = 'directory'

def read_config(file_name):
    try:
        with open(file_name, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"The file {file_name} was not found.")
    except json.JSONDecodeError:
        print(f"There was an error decoding the JSON from the file {file_name}.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    return None

def get_model_config(config, model_name=None):
    models = config["models"]["supported"]
    selected_model = next((model for model in models if model["name"] == model_name), models[0])
    return {
        "max_new_tokens": selected_model["metadata"]["max_new_tokens"],
        "max_input_token": selected_model["metadata"]["max_input_token"],
        "temperature": selected_model["metadata"]["temperature"]
    }

def get_data_path(config):
    return os.path.join(os.getcwd(), config["dataset"]["path"])

# Create an argument parser
parser = argparse.ArgumentParser(description='NVIDIA Chatbot Parameters')

# Add arguments
parser.add_argument('--base_url', type=str, required=False,
                    help="base url of the inference endpoint. format : http://remote-host:11434", default="http://localhost:11434")

args = parser.parse_args()

base_url = args.base_url

# read the app specific config
app_config = read_config(app_config_file)
streaming = app_config["streaming"]
similarity_top_k = app_config["similarity_top_k"]
is_chat_engine = app_config["is_chat_engine"]
embedded_model = app_config["embedded_model"]
embedded_dimension = app_config["embedded_dimension"]
score_threshold_filter = app_config["score_threshold_filter"]

# read model specific config
selected_model_name = None
selected_data_directory = None
config = read_config(model_config_file)
if os.path.exists(preference_config_file):
    perf_config = read_config(preference_config_file)
    selected_model_name = perf_config.get('models', {}).get('selected')
    selected_data_directory = perf_config.get('dataset', {}).get('path')

if selected_model_name == None:
    selected_model_name = config["models"].get("selected")

model_config = get_model_config(config, selected_model_name)
data_dir = config["dataset"]["path"] if selected_data_directory == None else selected_data_directory

llm = Ollama(model=selected_model_name, base_url=base_url)

#for tests
#from dotenv import load_dotenv
#load_dotenv()
#llm = OpenAI()

# create embeddings model object
embed_model = HuggingFaceEmbeddings(model_name=embedded_model)
service_context = ServiceContext.from_defaults(llm=llm, embed_model=embed_model,
                                               context_window=model_config["max_input_token"], chunk_size=512,
                                               chunk_overlap=200)
set_global_service_context(service_context)


def generate_inferance_engine(data, force_rewrite=False):
    """
       Initialize and return a FAISS-based inference engine.

       Args:
           data: The directory where the data for the inference engine is located.
           force_rewrite (bool): If True, force rewriting the index.

       Returns:
           The initialized inference engine.

       Raises:
           RuntimeError: If unable to generate the inference engine.
       """
    try:
        global engine
        faiss_storage = FaissEmbeddingStorage(data_dir=data,
                                              dimension=embedded_dimension)
        faiss_storage.initialize_index(force_rewrite=force_rewrite)
        engine = faiss_storage.get_engine(is_chat_engine=is_chat_engine, streaming=streaming,
                                          similarity_top_k=similarity_top_k)
    except Exception as e:
        raise RuntimeError(f"Unable to generate the inference engine: {e}")


# load the vectorstore index
generate_inferance_engine(data_dir)

def call_llm_streamed(query):
    partial_response = ""
    response = llm.stream_complete(query)
    for token in response:
        partial_response += token.delta
        yield partial_response

def generate_references(response: RESPONSE_TYPE, max_score = 1) -> list[dict] :
    # Aggregate scores by file
    file_sum_scores = defaultdict(float)
    file_count = defaultdict(int)
    file_page_nbs = {}
    for node in response.source_nodes:
        metadata = node.metadata
        if 'filename' in metadata:
            file_name = metadata['filename']
            file_sum_scores[file_name] += node.score
            file_count[file_name] += 1
            #print("%s p. %s has score %s"%(file_name, metadata.get("page_label"), str(node.score)))
            if metadata.get("page_label"):
                if not file_page_nbs.get(file_name) :
                    file_page_nbs[file_name] = set()
                file_page_nbs[file_name].add(int(metadata.get("page_label")))

    # compute avg
    # key is file name, value is avg score
    file_avg_scores = {}
    for k,v in file_sum_scores.items():
        file_avg_scores[k] = file_sum_scores.get(k)/file_count.get(k)

    file_links = []
    seen_files = set()  # Set to track unique file names

    # Generate links for the file with the lowest avg score
    for relative_file_name, avg_score in file_avg_scores.items():
        if avg_score < max_score:
            abs_path = Path(os.path.join(os.getcwd(), relative_file_name.replace('\\', '/')))
            file_name = str(abs_path)
            #file_name_without_ext = abs_path.stem
            if file_name not in seen_files:  # Ensure the file hasn't already been processed
                if data_source == 'directory':
                    file_link = file_name
                else:
                    exit("Wrong data_source type")
                file_links.append(file_link)
                seen_files.add(file_name)  # Mark file as processed

    result = []
    for x in seen_files:
        if file_page_nbs.get(x) :
            result.append({"filename" : x, "pages" : file_page_nbs.get(x) })
        else:
            result.append({"filename": x})
    return result

def chatbot(query, chat_history, session_id):
    if data_source == "nodataset":
        yield llm.complete(query).text
        return

    if is_chat_engine:
        response = engine.chat(query)
    else:
        response = engine.query(query)

    # generate file links if any
    file_links = generate_references(response)

    response_txt = str(response)
    if file_links:
        filename_list = [f.get("filename") for f in file_links]
        response_txt += "<br>Reference files:<br>" + "<br>".join(filename_list)
    if not file_links or len(file_links) == 0:  # If no file with a high score was found
        response_txt = llm.complete(query).text
    yield response_txt

def stream_chatbot(query, chat_history, session_id):
    if data_source == "nodataset":
        for response in call_llm_streamed(query):
            yield response
        return

    if is_chat_engine:
        response = engine.stream_chat(query)
    else:
        response = engine.query(query)

    partial_response = ""
    if len(response.source_nodes) == 0:
        response = llm.stream_complete(query)
        for token in response:
            partial_response += token.delta
            yield partial_response
    else:
        for token in response.response_gen:
            partial_response += token
            yield partial_response
            time.sleep(0.05)

        time.sleep(0.2)

        # generate file links if any
        file_links = generate_references(response, max_score=score_threshold_filter)

        if file_links:
            partial_response += "<br><br>Reference files:"
            for retrieved_file in file_links:
                partial_response += "<br>"
                partial_response += "<a href=\"file://%s\">%s</a>"\
                                    %(
                                        retrieved_file.get("filename"),
                                        retrieved_file.get("filename") + " [ p. " +
                                        ", ".join([str(x) for x in sorted(retrieved_file.get("pages"))]) + " ]" if retrieved_file.get("pages")
                                        else retrieved_file.get("filename")
                                    )

        yield  partial_response

    # call garbage collector after inference
    torch.cuda.empty_cache()
    gc.collect()

interface = MainInterface(chatbot=stream_chatbot if streaming else chatbot, streaming=streaming)

def on_shutdown_handler(session_id):
    global llm, service_context, embed_model, faiss_storage, engine
    import gc
    # if llm is not None:
    #     llm.unload_model()
    #     del llm
    # Force a garbage collection cycle
    gc.collect()


interface.on_shutdown(on_shutdown_handler)


def reset_chat_handler(session_id):
    global faiss_storage
    global engine
    print('reset chat called', session_id)
    if is_chat_engine == True:
        faiss_storage.reset_engine(engine)


interface.on_reset_chat(reset_chat_handler)


def on_dataset_path_updated_handler(source, new_directory, video_count, session_id):
    print('data set path updated to ', source, new_directory, video_count, session_id)
    global engine
    global data_dir
    if source == 'directory':
        if data_dir != new_directory:
            data_dir = new_directory
            generate_inferance_engine(data_dir)

interface.on_dataset_path_updated(on_dataset_path_updated_handler)

def on_model_change_handler(model, metadata, session_id):

    global llm, embedded_model, engine, data_dir, service_context

    llm = Ollama(model=model, base_url=base_url)
    service_context = ServiceContext.from_service_context(service_context=service_context, llm=llm)
    set_global_service_context(service_context)
    generate_inferance_engine(data_dir)


interface.on_model_change(on_model_change_handler)


def on_dataset_source_change_handler(source, path, session_id):

    global data_source, data_dir, engine
    data_source = source

    if data_source == "nodataset":
        print(' No dataset source selected', session_id)
        return
    
    print('dataset source updated ', source, path, session_id)
    
    if data_source == "directory":
        data_dir = path
    else:
        print("Wrong data type selected")
    generate_inferance_engine(data_dir)

interface.on_dataset_source_updated(on_dataset_source_change_handler)

def handle_regenerate_index(source, path, session_id):
    generate_inferance_engine(path, force_rewrite=True)
    print("on regenerate index", source, path, session_id)

interface.on_regenerate_index(handle_regenerate_index)
# render the interface
interface.render()
