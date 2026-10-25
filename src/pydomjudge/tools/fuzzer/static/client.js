const warn = function (message) {
    const alerts = $('.alerts');
    alerts.html(alerts.html() +
        "<div class=\"alert alert-success\"><a href=\"#\" class=\"close\" data-dismiss=\"alert\" aria-label=\"close\">&times;</a><strong>" + message + "</div>");
};

const display = function (cases) {
    const cases_tabs = $("#cases_tabs");
    const content = $("#cases_tab_contents");
    cases_tabs.empty();
    content.empty();
    if (cases === null) {
        return;
    }
    const keys = Object.keys(cases);

    let tabs_fragment = document.createDocumentFragment();
    let content_fragment = document.createDocumentFragment();

    for (let i = 0; i < keys.length; i++) {
        const output_name = keys[i];

        const tab = document.createElement("li")
        tab.className = "nav-item";
        tab.setAttribute("role", "presentation");

        const button = document.createElement("button");
        button.className = "nav-link";
        button.id = "case_" + output_name + "_tab";
        button.setAttribute("data-bs-toggle", "tab");
        button.setAttribute("data-bs-target", "#case_" + output_name);
        button.setAttribute("type", "button");
        button.setAttribute("role", "tab");
        button.appendChild(document.createTextNode(output_name));

        tab.appendChild(button);

        tabs_fragment.append(tab);

        const content = document.createElement("div");
        content.id = "case_" + output_name
        content.className = "tab-pane fade";
        content.setAttribute("role", "tabpanel");
        content.setAttribute("aria-labelledby", "case_" + output_name);

        if (i === 0) {
            tab.classList.add("active");
            content.classList.add("show", "active");
        }

        const text = document.createElement("textarea");
        text.className = "form-control";
        text.readOnly = true;
        text.wrap = "soft";
        text.rows = 10;
        text.style.width = "100%"
        text.appendChild(document.createTextNode(JSON.stringify(cases[keys[i]], null, 2)));

        content.appendChild(text);

        const copy_case = document.createElement("button");
        copy_case.appendChild(document.createTextNode("Case"));
        copy_case.className = "btn btn-secondary";
        const copy_answer = document.createElement("button");
        copy_answer.appendChild(document.createTextNode("Answer"));
        copy_answer.className = "btn btn-secondary";
        const copy_text = document.createElement("button");
        copy_text.appendChild(document.createTextNode("Text"));
        copy_text.className = "btn btn-primary"

        const files = Object.keys(cases[keys[i]]);
        let infile = "";
        let solution = "";
        for (let j = 0; j < files.length; j++) {
            let file = files[j];
            if (file.endsWith(".in")) {
                infile = cases[keys[i]][file]
            } else if (file.endsWith(".ans")) {
                solution = cases[keys[i]][file];
            }
        }

        copy_case.addEventListener("click", function (_) {
            navigator.clipboard.writeText(infile).catch(function (_) {
                console.log("Failed to write to clipboard")
            });
        })
        copy_answer.addEventListener("click", function (_) {
            navigator.clipboard.writeText(solution).catch(function (_) {
                console.log("Failed to write to clipboard")
            });
        })
        copy_text.addEventListener("click", function (_) {
            let text =
                "Here's a case to think about:\n" +
                infile +
                "\nThe correct answer should be:\n" +
                solution
            ;
            navigator.clipboard.writeText(text).catch(function (_) {
                console.log("Failed to write to clipboard")
            });
        })

        const buttons_div = document.createElement("div");
        buttons_div.style.display = "flex";
        buttons_div.style.flexDirection = "row";
        buttons_div.style.justifyContent = "flex-end";
        buttons_div.style.alignItems = "baseline";
        buttons_div.style.gap = "2px";

        buttons_div.appendChild(copy_case);
        buttons_div.appendChild(copy_answer);
        buttons_div.appendChild(copy_text);
        content.appendChild(buttons_div)
        content_fragment.append(content);
    }

    cases_tabs.append(tabs_fragment);
    content.append(content_fragment);
};

const source_change = function () {
    const source = $("#source").val();
    const source_lang = {
        val: function (key) {
            // Only languages of the repository can be chosen
            const select = $("#source_lang");
            return select.val(key in languages ? key : "unknown");
        }
    };

    const java_regex = /public\s+(static\s+)?(final\s+)?class\s+([a-zA-Z_$][a-zA-Z\d_$]*)/;
    const java_match = source.match(java_regex);
    if (java_match && java_match[3]) {
        console.log("Guessing source to be java, class name " + java_match[3]);
        source_lang.val("java").change();
        $("#java_name").val(java_match[3]);
        return;
    }

    const python_regex = [/sys\.stdin/, /\sprint\(/, /for\s+\S+\s+in\s+/];
    for (let regex of python_regex) {
        if (source.match(regex)) {
            console.log("Guessing source to be python, since it matches " + regex.toString());
            source_lang.val("python").change();
            return;
        }
    }

    const cpp_regex = [/#include/, /scanf/];
    for (let regex of cpp_regex) {
        if (source.match(regex)) {
            console.log("Guessing source to be cpp, since it matches " + regex.toString());
            source_lang.val("cpp").change();
            return;
        }
    }

    console.log("No source guess")
    source_lang.val("unknown").change();
}

// Id of the run shown, null when none runs
let current_run = null;

const show_progress = function (state) {
    const total = state.runs_total || 0;
    const done = state.runs_done || 0;
    const percent = total ? Math.round(100 * done / total) : 0;
    const bar = $("#progress_bar");
    bar.css("width", percent + "%").attr("aria-valuenow", percent);
    bar.toggleClass("bg-danger", (state.failures || 0) > 0);
    let text = done + " of " + total + " runs, " + (state.failures || 0) + " failed";
    if (state.cancelled) {
        text += " (cancelled)";
    }
    $("#progress_text").text(text);
};

const cancel_run = function () {
    if (current_run === null) {
        return;
    }
    const uuid = current_run;
    current_run = null;
    $.ajax({
        type: 'DELETE',
        url: "/submission/" + uuid,
        success: function (response) {
            if (response.success) {
                response.state.cancelled = true;
                show_progress(response.state);
                $("#log").val(response.state.log);
            }
            toggle_button(true);
        },
        error: function (_) {
            warn("Error in cancel request.");
        }
    });
};

const toggle_button = function (ready) {
    if (ready) {
        $('#submit-spinner').removeClass("spinner-border spinner-border-sm");
    } else {
        $('#submit-spinner').addClass("spinner-border spinner-border-sm");
    }
    $('#submit').prop("disabled", !ready);
    $('#cancel').prop("disabled", ready);
    if (ready) {
        current_run = null;
    }
}

const submit_problem = function () {
    // Problem
    const problem = $('#problem_name').val();
    if (!problem) {
        warn("No problem selected!");
        return;
    }

    // Secret file
    let secret_name = $('#secret_name').val();

    // Language: the repository's key, the file named main.<usual extension>,
    // Java files after their public class
    const source_lang = $('#source_lang').val();
    let lang = null;
    let source_name = "main";
    const language = languages[source_lang];
    if (language) {
        lang = language.key;
        if (lang === "java") {
            const classname = $("#java_name").val();
            if (!classname) {
                warn("No Java class name!");
                return;
            }
            source_name = classname + ".java";
        } else if (language.extensions.length) {
            source_name = "main." + language.extensions[0];
        }
    }

    const runs = parseInt($('#runs').val());

    console.log("Submitting as " + source_name);
    let source = {};
    source[source_name] = $('#source').val();

    const request = {
        "problem": problem,
        "language": lang,
        "sources": source,
        "case_name": secret_name,
        "runs": runs
    };

    let uuid = 0;
    current_run = null;

    const log = $("#log");

    let update_fun = function () {
        if (current_run !== uuid) {
            return;
        }
        $.ajax({
            type: 'GET',
            url: "/submission/" + uuid,
            success: function (response) {
                console.log("Got update" + JSON.stringify(response, null, 2));

                if (response.success) {
                    log.val(response.state.log);
                    show_progress(response.state);
                    if (response.state.finished) {
                        display(response.state.cases);
                        toggle_button(true);
                    } else {
                        setTimeout(update_fun, 1000);
                    }
                    // Scroll the textarea all the way down
                    log.scrollTop(log[0].scrollHeight);
                } else {
                    console.log("Unsuccessful update poll " + JSON.stringify(response, null, 2));
                    warn("Error in update request");
                    toggle_button(true);
                }
            },
            error: function (_) {
                warn("Error in update request.");
                toggle_button(true);
            }
        });
    };

    // Empty alerts
    $('.alerts').html("");

    // Empty result form
    log.val("");
    $("#cases").val("");
    $("#cases_tabs").empty();
    $("#cases_tab_contents").empty();

    // Initial submission request - if succeeded, will start periodical update requests via update fun
    $.ajax({
        type: 'POST',
        url: "/submission",
        contentType: 'application/json',
        data: JSON.stringify(request),
        success: function (response) {
            if (response.success) {
                toggle_button(false);
                $("#uuid").val(response.id);
                uuid = response.id;
                current_run = uuid;
                show_progress({runs_done: 0, runs_total: runs, failures: 0});
                console.log("Started fuzzing with id " + response.id);
                update_fun();
            } else {
                warn("Could not start fuzzing " + response.errors);
                console.log("Could not start fuzzing " + JSON.stringify(response, null, 2))
                toggle_button(true);
            }
        },
        error: function (_) {
            warn("Error in fuzzing request.");
        }
    });
}

function problem_change() {
    const problem_name = $("#problem_name").val();
    const secret_list = $("#secret_name");
    secret_list.prop("disabled", true);
    secret_list.empty();

    if (problems.indexOf(problem_name) < 0) {
        console.log("SKIP")
        console.log(problems)
        console.log(problem_name)
        return;
    }
    $.get("/problem/" + problem_name + "/seeds", function (data) {
        if (data.success) {
            secret_list.prop("disabled", false);
            for (const seed of data.seeds) {
                secret_list.append(new Option(seed, seed));
            }

            for (const seed of data.seeds) {
                if (seed.startsWith("small")) {
                    secret_list.val(seed).change();
                    return
                }
            }
            if (data.seeds.length) {
                secret_list.val(data.seeds[0]).change();
            }
        }
    });
}

let problems = [];
// The repository's languages by key
let languages = {};

function set_languages(data) {
    const select = $("#source_lang");
    select.empty();
    select.append(new Option("Unknown (detect)", "unknown"));
    languages = {};
    for (const language of data) {
        languages[language.key] = language;
        select.append(new Option(language.name, language.key));
    }
    select.val("unknown").change();
}

function set_problems(data) {
    problems.length = 0;

    const problem_list = $('#problem_list')
    let fragment = document.createDocumentFragment();

    for (const problem of data) {
        problems.push(problem);

        const option = document.createElement('option');
        option.textContent = problem;
        fragment.append(option);
    }
    problem_list.append(fragment);
    $('#problem_name').after(problem_list);
}

$(document).ready(function () {
    const source_input = $("#source");

    const source_change_listener = function (_) {
        source_change();
    };
    source_input.blur(source_change_listener);
    source_input.change(source_change_listener);

    $("#submit").click(function (event) {
        event.preventDefault();
        submit_problem();
    });
    $("#problem_name").blur(function (_) {
        problem_change();
    });

    $("#source_lang").change(function (_) {
        const java_name = $("#java_name");
        if ($("#source_lang").val() === "java") {
            java_name.prop("disabled", false);
        } else {
            java_name.prop("disabled", true);
            java_name.val("");
        }
    });

    $("#cancel").click(function (event) {
        event.preventDefault();
        cancel_run();
    });

    $.get('/languages', function (data) {
        if (data.success) {
            set_languages(data.languages);
        } else {
            warn("Failed to fetch languages")
        }
    });

    $.get('/problems', function (data) {
        if (data.success) {
            set_problems(data.problems);
            problem_change();
        } else {
            warn("Failed to fetch problems")
        }
    });
});
