package main

import (
	"log"
	backend "migrated.backend"
	"net/url"
	"os"
)

func main() {
	path := os.Getenv("DATABASE_URL")
	if path == "" {
		log.Fatal("DATABASE_URL is required")
	}
	parsed, err := url.Parse(path)
	if err != nil || parsed.Scheme != "file" || parsed.Host != "" {
		log.Fatal("absolute file: DATABASE_URL required")
	}
	app, err := backend.NewBenchApp(parsed.Path)
	if err != nil {
		log.Fatal(err)
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Fatal(app.Listen(":" + port))
}
