package qq

// Attachment is a file carried by an incoming message.
type Attachment struct {
	ContentType string `json:"content_type"`
	URL         string `json:"url"`
	Filename    string `json:"filename"`
	Size        int    `json:"size"`
}

type Author struct {
	ID           string `json:"id"`
	MemberOpenID string `json:"member_openid"`
	UserOpenID   string `json:"user_openid"`
}

// Message is the payload of GROUP_MESSAGE_CREATE, GROUP_AT_MESSAGE_CREATE and C2C_MESSAGE_CREATE.
type Message struct {
	ID          string       `json:"id"`
	Content     string       `json:"content"`
	GroupOpenID string       `json:"group_openid"`
	Author      Author       `json:"author"`
	Attachments []Attachment `json:"attachments"`
	Timestamp   string       `json:"timestamp"`
}

// Target says where a reply goes.
type Target struct {
	Group bool
	ID    string // group_openid or user_openid
}

func (t Target) base() string {
	if t.Group {
		return "/v2/groups/" + t.ID
	}
	return "/v2/users/" + t.ID
}

// TargetOf returns the reply target and a stable sender key for a message event.
func TargetOf(eventType string, m *Message) (Target, string) {
	if eventType == "C2C_MESSAGE_CREATE" {
		id := m.Author.UserOpenID
		if id == "" {
			id = m.Author.ID
		}
		return Target{Group: false, ID: id}, id
	}
	sender := m.Author.MemberOpenID
	if sender == "" {
		sender = m.Author.ID
	}
	return Target{Group: true, ID: m.GroupOpenID}, sender
}
