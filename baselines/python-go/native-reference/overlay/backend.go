// SPDX-License-Identifier: Apache-2.0
// Independent, unqualified Go reference for the four synthetic DRF source apps.
package backend

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"math/big"
	"net/url"
	"os/exec"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/gofiber/fiber/v3"
	_ "modernc.org/sqlite"
)

// Qualification makes a separate frozen copy with a negative-control value.
const controlMode = "native"

type obj = map[string]any
type queryer interface {
	Query(string, ...any) (*sql.Rows, error)
	QueryRow(string, ...any) *sql.Row
	Exec(string, ...any) (sql.Result, error)
}

func NewBenchApp(path string) (*fiber.App, error) {
	if controlMode == "python-proxy" {
		// A forbidden delegation attempt must fail the native gate even if HTTP matches.
		_ = exec.Command("/python", "-m", "http.server").Run()
	}
	u := &url.URL{Scheme: "file", Path: path}
	q := u.Query()
	q.Add("_pragma", "foreign_keys(1)")
	q.Add("_pragma", "busy_timeout(5000)")
	u.RawQuery = q.Encode()
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return nil, err
	}
	if err = db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	app := fiber.New(fiber.Config{DisableHeadAutoRegister: true, StrictRouting: true})
	var table string
	err = db.QueryRow("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('widgets_widget','posts_post','orders_order','wallets_wallet') ORDER BY name LIMIT 1").Scan(&table)
	if err != nil {
		db.Close()
		return nil, err
	}
	switch table {
	case "widgets_widget":
		widgets(app, db)
	case "posts_post":
		posts(app, db)
	case "orders_order":
		orders(app, db)
	case "wallets_wallet":
		wallets(app, db)
	default:
		return nil, fmt.Errorf("unknown source schema")
	}
	return app, nil
}
func reply(c fiber.Ctx, status int, body any) error {
	if status == 204 {
		return c.Status(status).Send(nil)
	}
	return c.Status(status).JSON(body)
}
func detail(c fiber.Ctx, status int, message string) error {
	return reply(c, status, obj{"detail": message})
}
func body(c fiber.Ctx) obj {
	var result obj
	decoder := json.NewDecoder(strings.NewReader(string(c.Body())))
	decoder.UseNumber()
	if decoder.Decode(&result) != nil || result == nil {
		return obj{}
	}
	return result
}
func text(value any, maximum int, blank bool) (string, string) {
	if value == nil {
		return "", "This field may not be null."
	}
	var s string
	switch v := value.(type) {
	case string:
		s = v
	case json.Number:
		s = string(v)
	default:
		return "", "Not a valid string."
	}
	s = strings.TrimSpace(s)
	if s == "" && !blank {
		return "", "This field may not be blank."
	}
	if maximum > 0 && utf8.RuneCountInString(s) > maximum {
		return "", fmt.Sprintf("Ensure this field has no more than %d characters.", maximum)
	}
	return s, ""
}
func integer(value any, minimum int64) (int64, string) {
	if value == nil {
		return 0, "This field may not be null."
	}
	s := ""
	switch v := value.(type) {
	case string:
		s = strings.TrimSpace(v)
	case json.Number:
		s = string(v)
	default:
		return 0, "A valid integer is required."
	}
	if dot := strings.IndexByte(s, '.'); dot >= 0 {
		if strings.Trim(s[dot+1:], "0") != "" {
			return 0, "A valid integer is required."
		}
		s = s[:dot]
	}
	n, e := strconv.ParseInt(s, 10, 64)
	if e != nil {
		return 0, "A valid integer is required."
	}
	if n < minimum {
		return 0, fmt.Sprintf("Ensure this value is greater than or equal to %d.", minimum)
	}
	return n, ""
}
func decimal(value any, maximum int, positive bool) (string, string) {
	if value == nil {
		return "", "This field may not be null."
	}
	s := ""
	switch v := value.(type) {
	case string:
		s = strings.TrimSpace(v)
	case json.Number:
		s = string(v)
	default:
		return "", "A valid number is required."
	}
	mantissa := s
	exponent := 0
	if idx := strings.IndexAny(s, "eE"); idx >= 0 {
		mantissa = s[:idx]
		var err error
		exponent, err = strconv.Atoi(s[idx+1:])
		if err != nil || exponent > 1000 || exponent < -1000 {
			return "", "A valid number is required."
		}
	}
	unsigned := strings.TrimPrefix(strings.TrimPrefix(mantissa, "-"), "+")
	parts := strings.Split(unsigned, ".")
	if len(parts) > 2 {
		return "", "A valid number is required."
	}
	fraction := ""
	if len(parts) == 2 {
		fraction = parts[1]
	}
	digitsText := parts[0] + fraction
	if digitsText == "" || strings.Trim(digitsText, "0123456789") != "" {
		return "", "A valid number is required."
	}
	significant := len(strings.TrimLeft(digitsText, "0"))
	if significant == 0 {
		significant = 1
	}
	scale := len(fraction) - exponent
	total := significant
	if scale < 0 {
		total -= scale
	} else if scale > total {
		total = scale
	}
	places := scale
	if places < 0 {
		places = 0
	}
	if total > maximum {
		return "", fmt.Sprintf("Ensure that there are no more than %d digits in total.", maximum)
	}
	if places > 2 {
		return "", "Ensure that there are no more than 2 decimal places."
	}
	if total-places > maximum-2 {
		return "", fmt.Sprintf("Ensure that there are no more than %d digits before the decimal point.", maximum-2)
	}
	number, ok := new(big.Rat).SetString(s)
	if !ok {
		return "", "A valid number is required."
	}
	if positive && number.Cmp(big.NewRat(1, 100)) < 0 {
		return "", "Ensure this value is greater than or equal to 0.01."
	}
	return number.FloatString(2), ""
}
func charField(p obj, values obj, errors obj, key string, max int, blank bool, required bool) {
	value, exists := p[key]
	if !exists {
		if required {
			errors[key] = []string{"This field is required."}
		}
		return
	}
	result, err := text(value, max, blank)
	if err != "" {
		errors[key] = []string{err}
	} else {
		values[key] = result
	}
}
func intField(p obj, values obj, errors obj, key string, min int64, required bool) {
	value, exists := p[key]
	if !exists {
		if required {
			errors[key] = []string{"This field is required."}
		}
		return
	}
	n, err := integer(value, min)
	if err != "" {
		errors[key] = []string{err}
	} else {
		values[key] = n
	}
}
func commit(tx *sql.Tx) error {
	if controlMode == "missing-write" {
		return tx.Rollback()
	}
	return tx.Commit()
}
func must(err error) {
	if err != nil {
		panic(err)
	}
}
func inserted(q queryer, statement string, args ...any) int64 {
	r, e := q.Exec(statement, args...)
	must(e)
	id, e := r.LastInsertId()
	must(e)
	return id
}
func rows(q queryer, statement string, args ...any) []obj {
	r, e := q.Query(statement, args...)
	must(e)
	defer r.Close()
	names, e := r.Columns()
	must(e)
	result := []obj{}
	for r.Next() {
		values := make([]any, len(names))
		pointers := make([]any, len(names))
		for i := range values {
			pointers[i] = &values[i]
		}
		must(r.Scan(pointers...))
		item := obj{}
		for i, name := range names {
			if b, ok := values[i].([]byte); ok {
				values[i] = string(b)
			}
			item[name] = values[i]
		}
		result = append(result, item)
	}
	must(r.Err())
	return result
}
func first(q queryer, statement string, args ...any) obj {
	r := rows(q, statement, args...)
	if len(r) == 0 {
		return nil
	}
	return r[0]
}
func money(v any) string {
	n, ok := new(big.Rat).SetString(fmt.Sprint(v))
	if !ok {
		panic("invalid database decimal")
	}
	return n.FloatString(2)
}

func widgets(app *fiber.App, db *sql.DB) {
	app.Get("/api/widgets/", func(c fiber.Ctx) error {
		return reply(c, 200, rows(db, "SELECT id,name,quantity FROM widgets_widget ORDER BY id"))
	})
	write := func(c fiber.Ctx) error {
		id := c.Params("id")
		current := obj{"name": "", "quantity": int64(0)}
		if id != "" {
			current = first(db, "SELECT id,name,quantity FROM widgets_widget WHERE id=?", id)
			if current == nil {
				return detail(c, 404, "No Widget matches the given query.")
			}
		}
		p := body(c)
		v := obj{}
		errors := obj{}
		required := c.Method() != "PATCH"
		charField(p, v, errors, "name", 80, false, required)
		intField(p, v, errors, "quantity", 0, required)
		if len(errors) > 0 {
			return reply(c, 400, errors)
		}
		for k, value := range v {
			current[k] = value
		}
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		status := 200
		if id == "" {
			current["id"] = inserted(tx, "INSERT INTO widgets_widget(name,quantity) VALUES(?,?)", current["name"], current["quantity"])
			status = 201
		} else {
			_, e = tx.Exec("UPDATE widgets_widget SET name=?,quantity=? WHERE id=?", current["name"], current["quantity"], id)
			must(e)
		}
		must(commit(tx))
		return reply(c, status, current)
	}
	app.Post("/api/widgets/", write)
	app.Patch("/api/widgets/:id/", write)
	app.Put("/api/widgets/:id/", write)
	app.Get("/api/widgets/:id/", func(c fiber.Ctx) error {
		item := first(db, "SELECT id,name,quantity FROM widgets_widget WHERE id=?", c.Params("id"))
		if item == nil {
			return detail(c, 404, "No Widget matches the given query.")
		}
		return reply(c, 200, item)
	})
	app.Delete("/api/widgets/:id/", func(c fiber.Ctx) error {
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		r, e := tx.Exec("DELETE FROM widgets_widget WHERE id=?", c.Params("id"))
		must(e)
		count, e := r.RowsAffected()
		must(e)
		if count == 0 {
			return detail(c, 404, "No Widget matches the given query.")
		}
		must(commit(tx))
		return reply(c, 204, nil)
	})
}
func posts(app *fiber.App, db *sql.DB) {
	app.Get("/api/", func(c fiber.Ctx) error {
		c.Set("Allow", "GET, HEAD, OPTIONS")
		return reply(c, 200, obj{"posts": "http://testserver/api/posts/"})
	})
	handler := func(c fiber.Ctx) error {
		id := c.Params("id")
		allow := "GET, POST, HEAD, OPTIONS"
		if id != "" {
			allow = "GET, PUT, PATCH, DELETE, HEAD, OPTIONS"
		}
		c.Set("Allow", allow)
		token := strings.Fields(c.Get("Authorization"))
		authError := "Authentication credentials were not provided."
		user := int64(0)
		if len(token) > 0 && strings.EqualFold(token[0], "Token") {
			if len(token) == 1 {
				authError = "Invalid token header. No credentials provided."
			} else if len(token) > 2 {
				authError = "Invalid token header. Token string should not contain spaces."
			} else {
				e := db.QueryRow("SELECT user_id FROM authtoken_token WHERE key=?", token[1]).Scan(&user)
				if e != nil {
					authError = "Invalid token."
				}
			}
		}
		if user == 0 {
			c.Set("WWW-Authenticate", "Token")
			return detail(c, 401, authError)
		}
		current := obj{}
		if id != "" {
			current = first(db, "SELECT id,author_id AS author,title,body FROM posts_post WHERE id=?", id)
			if current == nil {
				return detail(c, 404, "No Post matches the given query.")
			}
		}
		if c.Method() == "GET" {
			if id == "" {
				return reply(c, 200, rows(db, "SELECT id,author_id AS author,title,body FROM posts_post ORDER BY id"))
			}
			return reply(c, 200, current)
		}
		if id != "" && current["author"] != user {
			return detail(c, 403, "You do not have permission to perform this action.")
		}
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		if c.Method() == "DELETE" {
			_, e = tx.Exec("DELETE FROM posts_post WHERE id=?", id)
			must(e)
			must(commit(tx))
			return reply(c, 204, nil)
		}
		p := body(c)
		v := obj{}
		errors := obj{}
		required := c.Method() != "PATCH"
		charField(p, v, errors, "title", 100, false, required)
		charField(p, v, errors, "body", 400, true, false)
		if len(errors) > 0 {
			return reply(c, 400, errors)
		}
		if id == "" {
			current = obj{"author": user, "body": ""}
		}
		for k, value := range v {
			current[k] = value
		}
		status := 200
		if id == "" {
			current["id"] = inserted(tx, "INSERT INTO posts_post(author_id,title,body) VALUES(?,?,?)", user, current["title"], current["body"])
			status = 201
		} else {
			_, e = tx.Exec("UPDATE posts_post SET title=?,body=? WHERE id=?", current["title"], current["body"], id)
			must(e)
		}
		must(commit(tx))
		return reply(c, status, current)
	}
	for _, method := range []string{"GET", "POST"} {
		app.Add([]string{method}, "/api/posts/", handler)
	}
	for _, method := range []string{"GET", "PATCH", "PUT", "DELETE"} {
		app.Add([]string{method}, "/api/posts/:id/", handler)
	}
}

func validateChildren(value any, level int) ([]obj, any) {
	if value == nil {
		return nil, []string{"This field may not be null."}
	}
	list, ok := value.([]any)
	if !ok {
		return nil, obj{"non_field_errors": []string{fmt.Sprintf("Expected a list of items but got type \"%s\".", pytype(value))}}
	}
	output := []obj{}
	errors := obj{}
	for index, raw := range list {
		p, ok := raw.(map[string]any)
		if !ok {
			errors[strconv.Itoa(index)] = obj{"non_field_errors": []string{fmt.Sprintf("Invalid data. Expected a dictionary, but got %s.", pytype(raw))}}
			continue
		}
		v := obj{}
		e := obj{}
		required := []string{"code", "amount"}
		if level == 1 {
			required = []string{"sku", "quantity", "adjustments"}
		}
		for _, key := range required {
			if _, exists := p[key]; !exists {
				e[key] = []string{"This field is required."}
			}
		}
		if len(e) == 0 {
			if level == 1 {
				charField(p, v, e, "sku", 30, false, true)
				intField(p, v, e, "quantity", 1, true)
				charField(p, v, e, "description", 120, true, false)
				children, childErrors := validateChildren(p["adjustments"], 2)
				if childErrors != nil {
					e["adjustments"] = childErrors
				} else {
					v["adjustments"] = children
				}
				if _, exists := v["description"]; !exists {
					v["description"] = ""
				}
			} else {
				charField(p, v, e, "code", 20, false, true)
				charField(p, v, e, "note", 100, true, false)
				amount, errorText := decimal(p["amount"], 8, false)
				if errorText != "" {
					e["amount"] = []string{errorText}
				} else {
					v["amount"] = amount
				}
				if _, exists := v["note"]; !exists {
					v["note"] = ""
				}
			}
		}
		if len(e) > 0 {
			errors[strconv.Itoa(index)] = e
		} else {
			output = append(output, v)
		}
	}
	if len(errors) > 0 {
		return nil, errors
	}
	return output, nil
}
func pytype(v any) string {
	switch v.(type) {
	case string:
		return "str"
	case bool:
		return "bool"
	case json.Number:
		return "int"
	case []any:
		return "list"
	case map[string]any:
		return "dict"
	default:
		return "NoneType"
	}
}
func graph(q queryer, id any) obj {
	order := first(q, "SELECT id,reference,customer_note FROM orders_order WHERE id=?", id)
	if order == nil {
		return nil
	}
	items := rows(q, "SELECT id,sku,quantity,description FROM orders_orderitem WHERE order_id=? ORDER BY id", id)
	for _, item := range items {
		adjustments := rows(q, "SELECT id,code,amount,note FROM orders_adjustment WHERE item_id=? ORDER BY id", item["id"])
		for _, a := range adjustments {
			a["amount"] = money(a["amount"])
		}
		item["adjustments"] = adjustments
	}
	order["items"] = items
	return order
}
func createChildren(tx *sql.Tx, id any, items []obj) any {
	for i, item := range items {
		r, e := tx.Exec("INSERT INTO orders_orderitem(order_id,sku,quantity,description) VALUES(?,?,?,?)", id, item["sku"], item["quantity"], item["description"])
		if e != nil {
			return obj{"items": obj{strconv.Itoa(i): obj{"non_field_errors": []string{"The fields order, sku must make a unique set."}}}}
		}
		itemID, e := r.LastInsertId()
		must(e)
		for j, a := range item["adjustments"].([]obj) {
			_, e = tx.Exec("INSERT INTO orders_adjustment(item_id,code,amount,note) VALUES(?,?,?,?)", itemID, a["code"], a["amount"], a["note"])
			if e != nil {
				return obj{"items": obj{strconv.Itoa(i): obj{"adjustments": obj{strconv.Itoa(j): obj{"non_field_errors": []string{"The fields item, code must make a unique set."}}}}}}
			}
		}
	}
	return nil
}
func deleteChildren(tx *sql.Tx, id any) {
	_, e := tx.Exec("DELETE FROM orders_adjustment WHERE item_id IN (SELECT id FROM orders_orderitem WHERE order_id=?)", id)
	must(e)
	_, e = tx.Exec("DELETE FROM orders_orderitem WHERE order_id=?", id)
	must(e)
}
func orders(app *fiber.App, db *sql.DB) {
	app.Get("/api/", func(c fiber.Ctx) error { return reply(c, 200, obj{"orders": "http://testserver/api/orders/"}) })
	app.Get("/api/orders/", func(c fiber.Ctx) error {
		all := []obj{}
		for _, row := range rows(db, "SELECT id FROM orders_order ORDER BY id") {
			all = append(all, graph(db, row["id"]))
		}
		return reply(c, 200, all)
	})
	app.Get("/api/orders/:id/", func(c fiber.Ctx) error {
		g := graph(db, c.Params("id"))
		if g == nil {
			return detail(c, 404, "No Order matches the given query.")
		}
		return reply(c, 200, g)
	})
	write := func(c fiber.Ctx) error {
		id := c.Params("id")
		current := obj{"customer_note": ""}
		if id != "" {
			current = first(db, "SELECT id,reference,customer_note FROM orders_order WHERE id=?", id)
			if current == nil {
				return detail(c, 404, "No Order matches the given query.")
			}
		}
		p := body(c)
		v := obj{}
		errors := obj{}
		partial := c.Method() == "PATCH"
		charField(p, v, errors, "reference", 30, false, !partial)
		charField(p, v, errors, "customer_note", 200, true, false)
		if ref, exists := v["reference"]; exists {
			var count int
			must(db.QueryRow("SELECT count(*) FROM orders_order WHERE reference=? AND id!=?", ref, id).Scan(&count))
			if count > 0 {
				errors["reference"] = []string{"order with this reference already exists."}
			}
		}
		var children []obj
		childValue, replace := p["items"]
		if replace {
			var childErrors any
			children, childErrors = validateChildren(childValue, 1)
			if childErrors != nil {
				errors["items"] = childErrors
			}
		} else if !partial {
			errors["items"] = []string{"This field is required."}
		}
		if len(errors) > 0 {
			return reply(c, 400, errors)
		}
		for k, value := range v {
			current[k] = value
		}
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		status := 200
		if id == "" {
			current["id"] = inserted(tx, "INSERT INTO orders_order(reference,customer_note) VALUES(?,?)", current["reference"], current["customer_note"])
			status = 201
		} else {
			_, e = tx.Exec("UPDATE orders_order SET reference=?,customer_note=? WHERE id=?", current["reference"], current["customer_note"], id)
			must(e)
		}
		if replace {
			if id != "" {
				deleteChildren(tx, id)
			}
			if failure := createChildren(tx, current["id"], children); failure != nil {
				return reply(c, 400, failure)
			}
		}
		result := graph(tx, current["id"])
		must(commit(tx))
		return reply(c, status, result)
	}
	app.Post("/api/orders/", write)
	app.Put("/api/orders/:id/", write)
	app.Patch("/api/orders/:id/", write)
	app.Delete("/api/orders/:id/", func(c fiber.Ctx) error {
		id := c.Params("id")
		if graph(db, id) == nil {
			return detail(c, 404, "No Order matches the given query.")
		}
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		deleteChildren(tx, id)
		_, e = tx.Exec("DELETE FROM orders_order WHERE id=?", id)
		must(e)
		must(commit(tx))
		return reply(c, 204, nil)
	})
}
func tenant(c fiber.Ctx) (string, error) {
	value := c.Get("Authorization")
	t := map[string]string{"ApiKey north-key": "north", "ApiKey south-key": "south"}[value]
	if t != "" {
		return t, nil
	}
	c.Set("WWW-Authenticate", `ApiKey realm="wallets"`)
	message := "Invalid tenant key."
	if value == "" {
		message = "Authentication credentials were not provided."
	}
	return "", detail(c, 401, message)
}
func wallets(app *fiber.App, db *sql.DB) {
	app.Get("/api/wallets/", func(c fiber.Ctx) error {
		c.Set("Allow", "GET, HEAD, OPTIONS")
		t, e := tenant(c)
		if t == "" {
			return e
		}
		all := rows(db, "SELECT id,name,balance FROM wallets_wallet WHERE tenant=? ORDER BY id", t)
		for _, w := range all {
			w["balance"] = money(w["balance"])
		}
		return reply(c, 200, all)
	})
	app.Post("/api/transfers/", func(c fiber.Ctx) error {
		c.Set("Allow", "POST, OPTIONS")
		t, e := tenant(c)
		if t == "" {
			return e
		}
		p := body(c)
		v := obj{}
		errors := obj{}
		intField(p, v, errors, "source", 1, true)
		intField(p, v, errors, "destination", 1, true)
		charField(p, v, errors, "idempotency_key", 40, false, true)
		if a, ok := p["amount"]; !ok {
			errors["amount"] = []string{"This field is required."}
		} else {
			amount, errorText := decimal(a, 9, true)
			if errorText != "" {
				errors["amount"] = []string{errorText}
			} else {
				v["amount"] = amount
			}
		}
		if len(errors) == 0 && v["source"] == v["destination"] {
			errors["non_field_errors"] = []string{"Source and destination must differ."}
		}
		if len(errors) > 0 {
			return reply(c, 400, errors)
		}
		tx, e := db.Begin()
		must(e)
		defer tx.Rollback()
		source := first(tx, "SELECT id,balance FROM wallets_wallet WHERE tenant=? AND id=?", t, v["source"])
		dest := first(tx, "SELECT id,balance FROM wallets_wallet WHERE tenant=? AND id=?", t, v["destination"])
		c.Set("X-Idempotent-Replay", "false")
		if source == nil || dest == nil {
			return detail(c, 404, "Wallet not found.")
		}
		prior := first(tx, "SELECT id,source_id AS source,destination_id AS destination,amount,idempotency_key FROM wallets_transfer WHERE tenant=? AND idempotency_key=?", t, v["idempotency_key"])
		if prior != nil {
			prior["amount"] = money(prior["amount"])
			if prior["source"] != v["source"] || prior["destination"] != v["destination"] || prior["amount"] != v["amount"] {
				return detail(c, 409, "Idempotency key already used for a different transfer.")
			}
			c.Set("X-Idempotent-Replay", "true")
			return reply(c, 200, prior)
		}
		balance, _ := new(big.Rat).SetString(money(source["balance"]))
		amount, _ := new(big.Rat).SetString(v["amount"].(string))
		destination, _ := new(big.Rat).SetString(money(dest["balance"]))
		if balance.Cmp(amount) < 0 {
			return detail(c, 409, "Insufficient funds.")
		}
		_, e = tx.Exec("UPDATE wallets_wallet SET balance=? WHERE id=?", new(big.Rat).Sub(balance, amount).FloatString(2), v["source"])
		must(e)
		_, e = tx.Exec("UPDATE wallets_wallet SET balance=? WHERE id=?", new(big.Rat).Add(destination, amount).FloatString(2), v["destination"])
		must(e)
		id := inserted(tx, "INSERT INTO wallets_transfer(tenant,idempotency_key,source_id,destination_id,amount) VALUES(?,?,?,?,?)", t, v["idempotency_key"], v["source"], v["destination"], v["amount"])
		inserted(tx, "INSERT INTO wallets_auditevent(transfer_id,event) VALUES(?,?)", id, "transferred")
		result := obj{"id": id, "source": v["source"], "destination": v["destination"], "amount": v["amount"], "idempotency_key": v["idempotency_key"]}
		must(commit(tx))
		return reply(c, 201, result)
	})
}
