import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8003,
        workers=1,  # Use a single worker to avoid issues with multiple processes accessing the same database
        log_config=None # Disable uvicorn's default logging to avoid cluttering the output
    )
