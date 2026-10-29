% =====================================================================================================
% advising.lp : multi-term course planning (clingo 5)
%
% All credits and grade points are integers in tenths (3.0 credits -> 30, B+ 3.3 -> 33).
% Facts are written by advising_agent/facts.py; their source table is given in brackets.
%
%   term(T). term_type(T,Y).          planning terms 1..H, Y in {fall,spring,summer}   [academic_term]
%   published(T).                     T has lecture rows; plan at section level         [lecture]
%   course(C,Cr). level(C,L).         active courses                                    [course]
%   allowed_level(L).                 levels this student may take                      [policy]
%   offered_hist(C,Y).                C had a lecture in past terms of type Y           [lecture history]
%   lecture(T,C,N). full(T,N).        published section N of C in T; full section       [lecture, enrollment]
%   overlap(T,N1,N2).                 two sections of T meet at the same time           [lecture]
%   completed(C,P).                   best grade points earned in C (W, I excluded)     [enrollment+grade_scale]
%   in_progress(C).                   enrolled in the current term, no grade yet        [enrollment]
%   fixed(C,T,N).                     already registered for a planned term             [enrollment]
%   prereq(C,G,R,M).                  C needs, for each G, some R with points >= M      [course_prerequisite]
%   repeat_below_prereq_min.          a passed course may be repeated when its grade
%                                     is below some prerequisite minimum                [policy]
%   req_course(K,C). required(C).     degree plan rows; K = category                    [degree_requirement]
%   cat_min(K,N).                     credits needed from category K                    [program_category_requirement]
%   total_credits(N).                                                                   [program]
%   max_load(N). min_load(N).         per-term credit bounds (last term exempt from min) [policy, request]
%   target(T).                        hard graduation term (optional)                   [request]
%   prefer(C,W). avoid(C,W).          soft course preferences                           [request]
%   bad_slot(T,N,W).                  section N meets on an avoided day or time         [request]
%   all_objectives.                   use every objective level (omitted in the cautious run)
%   placeholder(C). ph_order(C1,C2).  generic free-elective slots, any term, no section
%   earliest(C,E). latest(C,L).       redundant term bounds (prune search, keep all plans)
%   grad_lb(L).                       the plan cannot end before term L (counting bound)
%
% Shown: take(C,T), sec(C,T,N), load(T,N), grad(T)
% =====================================================================================================

% ---------- history ----------
done(C) :- completed(C,P), P > 0.               % a grade earns credit when points > 0
done(C) :- in_progress(C).                      % assumption: in-progress courses are passed

retake(C) :- repeat_below_prereq_min, completed(C,P), P > 0, prereq(_,_,C,M), P < M.

open(C) :- course(C,_), not done(C).
open(C) :- retake(C).

% ---------- where a course can be taken ----------
can_take(C,T) :- open(C), published(T), lecture(T,C,N), not full(T,N).
can_take(C,T) :- open(C), term(T), not published(T), term_type(T,Y), offered_hist(C,Y), not placeholder(C).
can_take(C,T) :- open(C), placeholder(C), term(T).
ok_level(C) :- course(C,_), level(C,L), allowed_level(L).

% ---------- choice: each open course at most once ----------
{ take(C,T) : can_take(C,T), not too_early(C,T), not too_late(C,T) } 1 :- open(C), ok_level(C).
too_early(C,T) :- can_take(C,T), earliest(C,E), T < E.   % redundant bounds from facts.py
too_late(C,T)  :- can_take(C,T), latest(C,L), T > L.
take(C,T) :- fixed(C,T,_).

% ---------- prerequisites (a planned course is assumed to meet the minimum grade) ----------
met(R,M,T) :- prereq(_,_,R,M), completed(R,P), P >= M, term(T).
met(R,M,T) :- prereq(_,_,R,M), in_progress(R), term(T).
met(R,M,T) :- prereq(_,_,R,M), take(R,T0), term(T), T0 < T.

grp_ok(C,G,T) :- take(C,T), prereq(C,G,R,M), met(R,M,T).
:- take(C,T), prereq(C,G,_,_), not grp_ok(C,G,T).

% ---------- sections in published terms ----------
1 { sec(C,T,N) : lecture(T,C,N), not full(T,N) } 1 :- take(C,T), published(T), not fixed(C,T,_), not placeholder(C).
sec(C,T,N) :- fixed(C,T,N).
:- sec(C1,T,N1), sec(C2,T,N2), C1 != C2, overlap(T,N1,N2).

% free-elective slots are interchangeable: use them in order to avoid symmetric plans
take_le(C,T) :- take(C,T0), term(T), T0 <= T.
:- take(C2,T), ph_order(C1,C2), not take_le(C1,T).

% ---------- load ----------
load(T,S) :- term(T), S = #sum{ Cr,C : take(C,T), course(C,Cr) }.
:- load(T,S), max_load(M), S > M.

used(T) :- take(_,T).
used(T) :- used(T+1), term(T).
grad(T) :- used(T), not used(T+1).
:- used(T), not grad(T), load(T,S), min_load(M), S < M.
:- target(T0), used(T), T > T0.
:- grad_lb(L), term(L), not used(L).   % redundant lower bound from facts.py (credits needed / cap)

% ---------- graduation requirements, checked at the end of the plan ----------
fin(C) :- done(C).
fin(C) :- take(C,_).

:- required(C), not fin(C).
:- cat_min(K,N), #sum{ Cr,C : req_course(K,C), fin(C), course(C,Cr) } < N.
:- total_credits(N), #sum{ Cr,C : fin(C), course(C,Cr) } < N.

% ---------- objectives (higher priority first) ----------
#minimize{ 1@5,T : used(T) }.                           % graduate as early as possible
% The levels below apply only when all_objectives is given. The "must take next term" run omits it, so its
% cautious consequences mean "in every plan that graduates as early as possible".
#minimize{ W@4,C : take(C,_), avoid(C,W), all_objectives }.          % avoid disliked courses
#minimize{ W@4,T,N : sec(_,T,N), bad_slot(T,N,W), all_objectives }.  % avoid disliked days and times
#minimize{ -W@3,C : take(C,_), prefer(C,W), all_objectives }.        % include preferred courses
#minimize{ Cr@2,C : take(C,_), course(C,Cr), all_objectives }.       % no credits beyond what is needed
#minimize{ T@1,C : take(C,T), all_objectives }.                      % tie-break: take courses earlier

#show take/2.
#show sec/3.
#show load/2.
#show grad/1.
