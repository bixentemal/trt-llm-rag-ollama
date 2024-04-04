# 🚀 RAG using Ollama and LlamaIndex 🦙

This is a modified version of the https://github.com/NVIDIA/trt-llm-rag-windows.git using Ollama


Chat with RTX is a demo app that lets you personalize a GPT large language model (LLM) connected to your own content—docs, notes, videos, or other data. Leveraging retrieval-augmented generation (RAG), TensorRT-LLM, and RTX acceleration, you can query a custom chatbot to quickly get contextually relevant answers. And because it all runs locally on your Windows RTX PC or workstation, you’ll get fast and secure results.
Chat with RTX supports various file formats, including text, pdf, doc/docx, and xml. Simply point the application at the folder containing your files and it'll load them into the library in a matter of seconds. Additionally, you can provide the url of a YouTube playlist and the app will load the transcriptions of the videos in the playlist, enabling you to query the content they cover

### What is RAG? 🔍
Retrieval-augmented generation (RAG) for large language models (LLMs) seeks to enhance prediction accuracy by leveraging an external datastore during inference. This approach constructs a comprehensive prompt enriched with context, historical data, and recent or relevant knowledge.

## Getting Started

### Requirements :
- ollama installed on your local machine (https://ollama.com/)
- llama2 and mistral are predefined as selectable model so they must be installed upfront using ollama pull
```
ollama pull llama2
ollama pull mistral
```
- on linux tk must be installed (to allow root dir selection)
```
sudo apt-get install python3-tk
```

Prerequisites 
- [Python 3.10](https://www.python.org/downloads/windows/)

2. Install requirement.txt
```
pip install -r requirements.txt
```

### Run :

**Command:**
```
python app.py
```

## Adding your own data
- This app loads data from the dataset / directory into the vector store. To add support for your own data, replace the files in the dataset / directory with your own data. By default, the script uses llamaindex's SimpleDirectoryLoader which supports text files such as .txt, PDF, and so on.


This project requires additional third-party open source software projects as specified in the documentation. Review the license terms of these open source projects before use.
