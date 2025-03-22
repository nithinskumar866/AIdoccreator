import os
import langchain
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.llms import OpenAI
from langchain.chains import RetrievalQA
from dotenv import load_dotenv

# Load environment variables (API keys, etc.)
load_dotenv()

# Initialize OpenAI LLM
llm = OpenAI(temperature=0.2)

# Function to load documents
def load_documents(file_paths):
    docs = []
    for file_path in file_paths:
        if file_path.endswith(".pdf"):
            loader = PyPDFLoader(file_path)
        elif file_path.endswith(".txt"):
            loader = TextLoader(file_path)
        else:
            print(f"Unsupported file type: {file_path}")
            continue
        docs.extend(loader.load())
    return docs

# Load example documents
document_paths = ["doc1.pdf", "doc2.pdf"]  # Change as needed
documents = load_documents(document_paths)

# Split text for processing
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
docs = text_splitter.split_documents(documents)

# Convert text into embeddings
embeddings = OpenAIEmbeddings()
vector_db = FAISS.from_documents(docs, embeddings)
retriever = vector_db.as_retriever()

# Define a comparison chain
qa_chain = RetrievalQA(llm=llm, retriever=retriever)
query = "Compare the differences between the two documents and summarize key points."
response = qa_chain.run(query)

print("Comparison Results:\n", response)
