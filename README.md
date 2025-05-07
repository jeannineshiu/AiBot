# ElternLeben.de Conversational AI - Hackathon Project

## Transforming Digital Family Support in Germany (with Elternleben.de)

This project was developed for the hackathon focused on building a conversational AI system for **ElternLeben.de**, a non-profit organization dedicated to providing support, guidance, and expert knowledge for parents in Germany. The aim is to help parents create a loving and healthy environment for their children through trusted online counseling, educational content, and personalized programs.

## Project Goal

The primary goal of this project was to develop a conversational AI assistant that can effectively support parents by providing information, guidance, and access to ElternLeben.de's services.

## Evaluation Criteria

The solution was to be evaluated based on:

1.  **Conversational Intelligence:**
    * Natural dialog flow
    * Context maintenance
    * Appropriate response personalization
    * Accurate content recommendations
2.  **Service Integration:**
    * Seamless transitions from information to services
    * Effective booking/registration flows
    * Proper handling of user information
    * Analytics capabilities

## Development Journey & Attempts

This section outlines the iterative approach taken to build the chatbot.

### Attempt 1: Simple Echo Bot & Azure Familiarization

* **Objective:** To understand the fundamentals of the Microsoft Azure Bot Framework and establish a basic deployment pipeline.
* **Implementation:** A simple echo bot was developed and successfully deployed on Azure.
* **Learnings:** Gained familiarity with Azure Bot Service and the initial steps for bot deployment.

### Attempt 2: Building the Knowledge Base - Embeddings for RAG

* **Objective:** To process and prepare ElternLeben.de's content for a Retrieval Augmented Generation (RAG) system. This involved creating a searchable index of embeddings.
* **Implementation:**
    * Leveraged code from the [Azure Search OpenAI Demo](https://github.com/Azure-Samples/azure-search-openai-demo), specifically the `prepdocs.py` script and its associated `filestrategy.py` for data processing.
    * Data was split into manageable chunks.
    * Azure OpenAI's `text-embedding-ada-002` model was used to compute embeddings for these chunks.
    * The generated embeddings and content chunks were stored in an Azure AI Search index.
* **Outcome:** Successfully created an embeddings index in Azure AI Search, forming the knowledge base for the RAG solution.

### Attempt 3: RAG Solution Integration & Challenges

* **Objective:** To integrate the RAG pattern with the bot, enabling it to retrieve relevant information from the knowledge base and generate contextual responses using a powerful language model.
* **Implementation:**
    * The RAG solution was integrated into the bot's backend. Key components involved:
        * `app/backend/app.py` (main application logic)
        * `app/backend/approaches/` (different RAG strategies and interaction logic)
        * `app/backend/core/authentication.py` (handling security and access)
    * Azure AI Search was used to query the previously created index.
    * Azure AI Services provided access to the `gpt-4` model for generating responses based on retrieved context and the `text-embedding-ada-002` model for processing user queries if needed.
* **Challenge Encountered:** Faced OpenAI rate limit issues. An increase in quota is required to fully test and operate the RAG-powered bot at scale. This involves submitting a request to Azure.

## Technologies Used

* **Cloud Platform:** Microsoft Azure
* **Bot Framework:** Azure Bot Service
* **Language Models & Embeddings:**
    * Azure OpenAI Service
        * `gpt-4` (for generation)
        * `text-embedding-ada-002` (for embeddings)
* **Search & Data Storage:** Azure AI Search (formerly Azure Cognitive Search) for storing and querying embeddings.
* **Backend Language:** Python
* **Key Python Scripts/Modules:**
    * `predocs.py` & `filestrategy.py` (from Azure Search OpenAI Demo for data preparation)
    * `app/backend/app.py`
    * `app/backend/approaches/`
    * `app/backend/core/authentication.py`

## Future Work & Next Steps

* **Address OpenAI Rate Limits:** Submit the necessary request to Azure to increase the OpenAI service quota.
* **Refine Conversational Flow:** Continuously improve natural language understanding, context management, and response personalization.
* **Enhance Service Integration:** Develop robust flows for booking/registration and other services offered by ElternLeben.de.
* **Implement Analytics:** Integrate analytics to track usage and gather insights for improvement.
* **Thorough Testing:** Conduct comprehensive testing based on the hackathon's evaluation criteria.

