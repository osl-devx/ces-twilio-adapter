FROM python:3.13-slim

# Env vars for python to not write pycs and to flush logs
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the locale to a UTF-8 compatible one
ENV LANG C.UTF-8
ENV LANGUAGE C.UTF-8
ENV LC_ALL C.UTF-8

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY . .

# Expose the port the app runs on
EXPOSE 8080

# Run the application with a production-ready server (Gunicorn + Uvicorn)
# The number of workers is often set to (2 * number_of_cores) + 1.
# Cloud Run provides this via an environment variable.
CMD ["gunicorn", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8080", "main:app"]